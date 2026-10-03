import { hydrateStable, materialize, type Rows } from '@harak2/shared'
import { type Document, OutgoingMessage, Server } from '@hocuspocus/server'
import { randomUUID, timingSafeEqual } from 'node:crypto'

import * as Y from 'yjs'

import { AuthenticationRefused, type Grant, verifyToken } from './auth.js'
import type { DocumentStore } from './store.js'

export interface CollabServerOptions {
  port: number
  tokenSecret: string
  /** Secret Django presents on the internal endpoints (freeze, unfreeze, snapshot, lock). */
  serviceSecret?: string
  store?: DocumentStore
  name?: string
  /** Quiet period before a changed document is saved, and the longest it may wait. */
  debounceMs?: number
  maxDebounceMs?: number
  /** A save that did not reach Django is retried after this long, doubling up to the maximum. */
  retryBaseMs?: number
  retryMaxMs?: number
  /** A freeze Django never ends (it crashed mid-submission) is checked against Django after this long. */
  freezeTtlMs?: number
  log?: (event: string, fields: Record<string, unknown>) => void
}

export interface ConnectionContext {
  grant: Grant
}

export interface DocumentStatus {
  versionId: number
  locked: boolean
  lastSave: 'never' | 'saved' | 'failed'
  lastError: string | null
  lastErrorCode: string | null
  /** The latest content is not stored in Django: unloading the document would lose it. */
  unsaved: boolean
  /** The failure may pass by itself (Django unreachable), so the save is retried. */
  retryable: boolean
  attempts: number
  /** Who changed the document last; saves made without an editor (retries, snapshots) are theirs. */
  lastActor: string | null
}

export type Snapshot =
  | { status: 'snapshot'; seq: number; state: string; rows: Rows; actor_id: string | null }
  | { status: 'not_loaded' }
  | { status: 'failed'; error: string; code: string }

const NAME = /^program-version:(\d+)$/

export function versionIdOf(documentName: string): number {
  const match = NAME.exec(documentName)
  if (!match) throw new Error(`not a program version document: ${documentName}`)
  return Number(match[1])
}

const message = (error: unknown) => (error instanceof Error ? error.message : String(error))

export class CollabService {
  readonly server: Server<ConnectionContext>
  private readonly status = new Map<string, DocumentStatus>()
  /** Open freezes per document, each with the timer that checks on it if Django never ends it. */
  private readonly freezes = new Map<string, Map<string, NodeJS.Timeout>>()
  private readonly retries = new Map<string, NodeJS.Timeout>()
  private readonly log: NonNullable<CollabServerOptions['log']>
  private lastSeq = 0
  private stopping = false

  constructor(private readonly options: CollabServerOptions) {
    this.log = options.log ?? ((event, fields) => console.log(JSON.stringify({ event, ...fields })))
    this.server = new Server<ConnectionContext>({
      port: options.port,
      name: options.name ?? 'harak2-collab',
      quiet: true,
      // Shutdown is handled by main.ts through destroy(), which bounds how long it waits.
      stopOnSignals: false,
      debounce: options.debounceMs ?? 2000,
      maxDebounce: options.maxDebounceMs ?? 10_000,
      onAuthenticate: async ({ token, documentName, connectionConfig }) => {
        try {
          const grant = await verifyToken(token, documentName, options.tokenSecret)
          connectionConfig.readOnly = grant.mode === 'read' || this.isHeld(documentName)
          return { grant }
        } catch (error) {
          if (error instanceof AuthenticationRefused) throw new Error('unauthorized')
          throw error
        }
      },
      // Every message, including those queued while the document loaded, meets the current lock and freeze.
      beforeHandleMessage: async ({ documentName, connection }) => {
        if (this.isHeld(documentName)) connection.readOnly = true
      },
      connected: async ({ documentName, connection }) => {
        const status = this.status.get(documentName)
        if (this.isHeld(documentName)) connection.readOnly = true
        // Someone who opens the document now learns what the others were told. (A locked version needs no
        // news: the page knows its status, and 'locked' means it changed while open.)
        if (!status?.locked && this.isFrozen(documentName)) connection.sendStateless(JSON.stringify({ type: 'frozen' }))
        if (status?.lastSave === 'failed') connection.sendStateless(JSON.stringify(this.failureMessage(status)))
      },
      onLoadDocument: async ({ documentName, document }) => {
        const versionId = versionIdOf(documentName)
        const status: DocumentStatus = {
          versionId,
          locked: false,
          lastSave: 'never',
          lastError: null,
          lastErrorCode: null,
          unsaved: false,
          retryable: false,
          attempts: 0,
          lastActor: null,
        }
        this.status.set(documentName, status)
        if (!options.store) return document
        const loaded = await options.store.load(versionId)
        // A lock that arrived while Django answered stays: the answer may predate it.
        status.locked = status.locked || !loaded.editable
        if (loaded.state) Y.applyUpdate(document, Buffer.from(loaded.state, 'base64'))
        // The same rows always build the same document, so an editor holding a copy from an earlier load
        // merges into this one instead of beside it.
        else if (loaded.rows) hydrateStable(loaded.rows, document)
        return document
      },
      onChange: async ({ documentName, context }) => {
        const status = this.status.get(documentName)
        const userId = (context as Partial<ConnectionContext> | undefined)?.grant?.userId
        if (status && userId) status.lastActor = userId
      },
      onStoreDocument: async ({ documentName, document, lastContext }) => {
        const status = await this.store(documentName, document, lastContext?.grant?.userId ?? null)
        if (status?.unsaved && status.retryable && !this.stopping) {
          this.scheduleRetry(documentName)
          // Hocuspocus unloads a document only after a store that did not throw: this one keeps its edits.
          throw new Error(`${documentName} is not saved yet: ${status.lastError}`)
        }
      },
      beforeUnloadDocument: async ({ documentName }) => {
        const status = this.status.get(documentName)
        if (!status?.unsaved) return
        if (status.retryable && !this.stopping) throw new Error(`${documentName} keeps unsaved changes`)
        this.log('collab.unsaved_changes_dropped', { document: documentName, error: status.lastError })
      },
      onStateless: async ({ connection, document, payload }) => {
        // Clients announce changes that live outside the document (comments) so the others refresh.
        let type: unknown
        try {
          type = JSON.parse(payload).type
        } catch {
          return
        }
        if (type === 'comments-changed') document.broadcastStateless(payload, (other) => other !== connection)
      },
      afterUnloadDocument: async ({ documentName }) => {
        this.status.delete(documentName)
        clearTimeout(this.retries.get(documentName))
        this.retries.delete(documentName)
      },
      onRequest: async ({ request, response }) => {
        const reply = (status: number, body: unknown) => {
          // Internal calls are rare; closing avoids clients reusing a socket to a restarted service.
          response.writeHead(status, { 'Content-Type': 'application/json', Connection: 'close' })
          response.end(JSON.stringify(body))
        }
        const url = new URL(request.url ?? '/', 'http://collab.internal')
        if (url.pathname === '/health') {
          reply(200, { status: 'ok', service: 'collab' })
          // A rejection with no value tells Hocuspocus the request was handled here.
          throw undefined
        }
        const internal = /^\/internal\/documents\/([^/]+)\/(freeze|unfreeze|snapshot|lock)$/.exec(url.pathname)
        if (internal && request.method === 'POST') {
          const name = decodeURIComponent(internal[1])
          if (!this.authorizedService(request.headers.authorization)) reply(403, { error: 'forbidden' })
          else if (!NAME.test(name)) reply(404, { error: 'not_found' })
          else {
            try {
              reply(200, this.internal(name, internal[2] as InternalAction, url.searchParams.get('token')))
            } catch (error) {
              // Django gets an answer it can act on; the service keeps running.
              this.log('collab.internal_failed', { document: name, action: internal[2], error: message(error) })
              reply(500, { status: 'failed', error: message(error), code: 'collab_error' })
            }
          }
          throw undefined
        }
      },
    })
  }

  private authorizedService(header: string | undefined): boolean {
    const secret = this.options.serviceSecret
    if (!secret || !header?.startsWith('Service ')) return false
    const given = Buffer.from(header.slice('Service '.length))
    const expected = Buffer.from(secret)
    return given.length === expected.length && timingSafeEqual(given, expected)
  }

  /**
   * Django's calls. None of them calls back into Django, so a Django worker waiting on one never needs another.
   * - freeze: no edits are accepted until unfreeze or lock; the answer is the document as it stands.
   * - unfreeze: ends one freeze (the draft stays a draft); editing resumes when no other freeze holds it.
   * - snapshot: the document as it stands, without stopping anyone.
   * - lock: the version left draft; nothing is accepted any more.
   */
  private internal(documentName: string, action: InternalAction, token: string | null) {
    switch (action) {
      case 'freeze': {
        const held = this.freeze(documentName)
        return { ...this.snapshot(documentName), token: held }
      }
      case 'unfreeze':
        if (token) this.unfreeze(documentName, token)
        return { status: 'unfrozen', frozen: this.isFrozen(documentName) }
      case 'snapshot':
        return this.snapshot(documentName)
      case 'lock':
        this.lock(documentName)
        return { status: 'locked', loaded: this.server.hocuspocus.documents.has(documentName) }
    }
  }

  statusOf(documentName: string): DocumentStatus | undefined {
    return this.status.get(documentName)
  }

  isFrozen(documentName: string): boolean {
    return (this.freezes.get(documentName)?.size ?? 0) > 0
  }

  private isHeld(documentName: string): boolean {
    return this.isFrozen(documentName) || Boolean(this.status.get(documentName)?.locked)
  }

  /** Numbers what is sent to Django in order, across restarts too (it starts from the clock). */
  private nextSeq(): number {
    this.lastSeq = Math.max(Date.now() * 1000, this.lastSeq + 1)
    return this.lastSeq
  }

  snapshot(documentName: string): Snapshot {
    const document = this.server.hocuspocus.documents.get(documentName)
    if (!document || document.isLoading) return { status: 'not_loaded' }
    let rows: Rows
    try {
      rows = materialize(document)
    } catch (error) {
      return { status: 'failed', error: `materialize: ${message(error)}`, code: 'document_invalid' }
    }
    return {
      status: 'snapshot',
      seq: this.nextSeq(),
      state: Buffer.from(Y.encodeStateAsUpdate(document)).toString('base64'),
      rows,
      actor_id: this.status.get(documentName)?.lastActor ?? null,
    }
  }

  /** Materializes the document and hands state and rows to Django. */
  async store(documentName: string, document: Y.Doc, actorId: string | null): Promise<DocumentStatus | undefined> {
    const status = this.status.get(documentName)
    if (!status || status.locked || !this.options.store) return status
    // While frozen, Django takes the document from the freeze itself; saving it as well would only race.
    if (this.isFrozen(documentName)) return status
    const actor = actorId ?? status.lastActor
    const seq = this.nextSeq()
    let rows: Rows
    try {
      rows = materialize(document)
    } catch (error) {
      const failure = { error: `materialize: ${message(error)}`, code: 'document_invalid', stateSaved: false, retryable: false }
      await this.options.store.reportFailure(status.versionId, failure.error, failure.code).catch(() => undefined)
      this.failed(documentName, status, failure)
      return status
    }
    const before = status.lastSave
    let result
    try {
      result = await this.options.store.save(status.versionId, Y.encodeStateAsUpdate(document), rows, actor, seq)
    } catch (error) {
      result = { status: 'failed' as const, error: message(error), code: 'save_unavailable', stateSaved: false, retryable: true }
    }
    if (result.status === 'saved') {
      Object.assign(status, { lastSave: 'saved', lastError: null, lastErrorCode: null, unsaved: false, retryable: false, attempts: 0 })
      clearTimeout(this.retries.get(documentName))
      this.retries.delete(documentName)
      if (before !== 'saved') this.tell(documentName, { type: 'saved' })
    } else if (result.status === 'locked') {
      this.lock(documentName)
    } else {
      this.failed(documentName, status, result)
    }
    return status
  }

  private failed(
    documentName: string,
    status: DocumentStatus,
    failure: { error: string; code: string; stateSaved: boolean; retryable: boolean },
  ) {
    Object.assign(status, {
      lastSave: 'failed',
      lastError: failure.error,
      lastErrorCode: failure.code,
      // Django keeps the state it was sent even when it refuses the rows; otherwise the content is only here.
      unsaved: !failure.stateSaved,
      retryable: failure.retryable,
    })
    this.log('collab.save_failed', { document: documentName, code: failure.code, error: failure.error })
    // Editors show it at once; submission stays blocked until a later save succeeds.
    this.tell(documentName, this.failureMessage(status))
  }

  private failureMessage(status: DocumentStatus) {
    return { type: 'save-failed', error: status.lastError, code: status.lastErrorCode }
  }

  private tell(documentName: string, body: Record<string, unknown>) {
    this.server.hocuspocus.documents.get(documentName)?.broadcastStateless(JSON.stringify(body))
  }

  private scheduleRetry(documentName: string) {
    const status = this.status.get(documentName)
    if (!status || this.retries.has(documentName)) return
    status.attempts += 1
    const base = this.options.retryBaseMs ?? 1000
    const delay = Math.min(base * 2 ** (status.attempts - 1), this.options.retryMaxMs ?? 60_000)
    const timer = setTimeout(() => {
      this.retries.delete(documentName)
      const document = this.server.hocuspocus.documents.get(documentName)
      if (!document || this.stopping) return
      // Through Hocuspocus, so the retry runs under the document's save lock and unloads it once it succeeds.
      void this.server.hocuspocus.storeDocumentHooks(document, this.storePayload(document), true)
    }, delay)
    timer.unref?.()
    this.retries.set(documentName, timer)
  }

  private storePayload(document: Document) {
    return {
      instance: this.server.hocuspocus,
      clientsCount: document.getConnectionsCount(),
      document,
      documentName: document.name,
      lastContext: {},
      lastTransactionOrigin: undefined,
    }
  }

  /** No edits are accepted until the freeze ends. Returns the token that ends it. */
  freeze(documentName: string): string {
    const token = randomUUID()
    const held = this.freezes.get(documentName) ?? new Map<string, NodeJS.Timeout>()
    this.freezes.set(documentName, held)
    const first = held.size === 0
    held.set(token, this.expiry(documentName, token))
    const document = this.server.hocuspocus.documents.get(documentName)
    document?.connections.forEach((_value, connection) => {
      connection.readOnly = true
    })
    if (first && !this.status.get(documentName)?.locked) this.tell(documentName, { type: 'frozen' })
    return token
  }

  unfreeze(documentName: string, token: string): void {
    const held = this.freezes.get(documentName)
    if (!held?.has(token)) return
    clearTimeout(held.get(token))
    held.delete(token)
    if (held.size > 0) return
    this.freezes.delete(documentName)
    this.resume(documentName)
  }

  /** Editing resumes as each editor's grant allows, and what they typed during the freeze is asked for again. */
  private resume(documentName: string): void {
    if (this.status.get(documentName)?.locked) return
    const document = this.server.hocuspocus.documents.get(documentName)
    if (!document) return
    document.connections.forEach((_value, connection) => {
      connection.readOnly = (connection.context as ConnectionContext | undefined)?.grant?.mode !== 'write'
      // Updates refused while frozen are still in the editor's copy: a sync step 1 makes it send them back.
      connection.send(new OutgoingMessage(documentName).createSyncMessage().writeFirstSyncStepFor(document).toUint8Array())
    })
    this.tell(documentName, { type: 'unfrozen' })
    // Content from before the freeze may have reached Django only through the freeze; saving again is harmless.
    void this.server.hocuspocus.storeDocumentHooks(document, this.storePayload(document))
  }

  /** A freeze Django never ended: lock if the version left draft meanwhile, otherwise resume editing. */
  private expiry(documentName: string, token: string): NodeJS.Timeout {
    const timer = setTimeout(async () => {
      if (this.stopping || !this.freezes.get(documentName)?.has(token)) return
      const hocuspocus = this.server.hocuspocus
      if (!hocuspocus.documents.has(documentName) && !hocuspocus.loadingDocuments.has(documentName)) {
        // Nobody has it open, so there is nothing to hold: whoever opens it next loads its status from Django.
        this.unfreeze(documentName, token)
        return
      }
      let editable: boolean
      try {
        editable = this.options.store ? (await this.options.store.load(versionIdOf(documentName))).editable : true
      } catch (error) {
        this.log('collab.freeze_check_failed', { document: documentName, error: message(error) })
        this.freezes.get(documentName)?.set(token, this.expiry(documentName, token))
        return
      }
      if (!this.freezes.get(documentName)?.has(token)) return
      this.log('collab.freeze_expired', { document: documentName, editable })
      if (editable) this.unfreeze(documentName, token)
      else this.lock(documentName)
    }, this.options.freezeTtlMs ?? 120_000)
    timer.unref?.()
    return timer
  }

  /** No further edits are accepted: every open connection and every new one is read-only. */
  lock(documentName: string): void {
    for (const timer of this.freezes.get(documentName)?.values() ?? []) clearTimeout(timer)
    this.freezes.delete(documentName)
    const status = this.status.get(documentName)
    if (status) {
      if (status.unsaved) this.log('collab.unsaved_changes_dropped', { document: documentName, error: status.lastError })
      // Nothing can be saved any more, so nothing is kept in memory for a save.
      Object.assign(status, { locked: true, unsaved: false, retryable: false })
    }
    clearTimeout(this.retries.get(documentName))
    this.retries.delete(documentName)
    const document: Document | undefined = this.server.hocuspocus.documents.get(documentName)
    document?.connections.forEach((_value, connection) => {
      connection.readOnly = true
    })
    // Tell every open editor, so it switches to read-only instead of typing into the void.
    document?.broadcastStateless(JSON.stringify({ type: 'locked' }))
  }

  listen() {
    return this.server.listen()
  }

  /**
   * Stops accepting connections and saves what it can within the time allowed. A save that still fails is
   * logged and dropped: holding the process open would not bring Django back.
   */
  async destroy(timeoutMs = 8000): Promise<void> {
    this.stopping = true
    for (const timer of this.retries.values()) clearTimeout(timer)
    this.retries.clear()
    for (const held of this.freezes.values()) for (const timer of held.values()) clearTimeout(timer)
    let timer: NodeJS.Timeout | undefined
    const timedOut = new Promise<'timeout'>((resolve) => {
      timer = setTimeout(() => resolve('timeout'), timeoutMs)
    })
    const outcome = await Promise.race([this.server.destroy().then(() => 'done' as const), timedOut])
    clearTimeout(timer)
    if (outcome === 'timeout') {
      this.log('collab.shutdown_timeout', { documents: [...this.server.hocuspocus.documents.keys()] })
    }
  }
}

type InternalAction = 'freeze' | 'unfreeze' | 'snapshot' | 'lock'

/** Kept for callers that only need a running server. */
export function createCollabServer(options: CollabServerOptions): CollabService {
  return new CollabService(options)
}
