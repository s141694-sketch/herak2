import { hydrate, materialize } from '@harak2/shared'
import { type Document, Server } from '@hocuspocus/server'
import { timingSafeEqual } from 'node:crypto'

import * as Y from 'yjs'

import { AuthenticationRefused, type Grant, verifyToken } from './auth.js'
import type { DocumentStore } from './store.js'

export interface CollabServerOptions {
  port: number
  tokenSecret: string
  /** Secret Django presents on the internal flush and lock endpoints. */
  serviceSecret?: string
  store?: DocumentStore
  name?: string
  /** Quiet period before a changed document is saved, and the longest it may wait. */
  debounceMs?: number
  maxDebounceMs?: number
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
}

const NAME = /^program-version:(\d+)$/

export function versionIdOf(documentName: string): number {
  const match = NAME.exec(documentName)
  if (!match) throw new Error(`not a program version document: ${documentName}`)
  return Number(match[1])
}

export class CollabService {
  readonly server: Server<ConnectionContext>
  private readonly status = new Map<string, DocumentStatus>()
  private readonly log: NonNullable<CollabServerOptions['log']>

  constructor(private readonly options: CollabServerOptions) {
    this.log = options.log ?? ((event, fields) => console.log(JSON.stringify({ event, ...fields })))
    this.server = new Server<ConnectionContext>({
      port: options.port,
      name: options.name ?? 'harak2-collab',
      quiet: true,
      // Shutdown is handled by main.ts, which saves pending documents first.
      stopOnSignals: false,
      debounce: options.debounceMs ?? 2000,
      maxDebounce: options.maxDebounceMs ?? 10_000,
      onAuthenticate: async ({ token, documentName, connectionConfig }) => {
        try {
          const grant = await verifyToken(token, documentName, options.tokenSecret)
          connectionConfig.readOnly = grant.mode === 'read'
          return { grant }
        } catch (error) {
          if (error instanceof AuthenticationRefused) throw new Error('unauthorized')
          throw error
        }
      },
      connected: async ({ documentName, connection }) => {
        if (this.status.get(documentName)?.locked) connection.readOnly = true
      },
      onLoadDocument: async ({ documentName, document }) => {
        const versionId = versionIdOf(documentName)
        const status: DocumentStatus = { versionId, locked: false, lastSave: 'never', lastError: null }
        this.status.set(documentName, status)
        if (!options.store) return document
        const loaded = await options.store.load(versionId)
        status.locked = !loaded.editable
        if (loaded.state) Y.applyUpdate(document, Buffer.from(loaded.state, 'base64'))
        else if (loaded.rows) hydrate(loaded.rows, document)
        return document
      },
      onStoreDocument: async ({ documentName, document, lastContext }) => {
        await this.store(documentName, document, lastContext?.grant?.userId ?? null)
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
      },
      onRequest: async ({ request, response }) => {
        const reply = (status: number, body: unknown) => {
          response.writeHead(status, { 'Content-Type': 'application/json' })
          response.end(JSON.stringify(body))
        }
        if (request.url === '/health') {
          reply(200, { status: 'ok', service: 'collab' })
          // A rejection with no value tells Hocuspocus the request was handled here.
          throw undefined
        }
        const internal = /^\/internal\/documents\/([^/]+)\/(flush|lock)$/.exec(request.url ?? '')
        if (internal && request.method === 'POST') {
          if (!this.authorizedService(request.headers.authorization)) reply(403, { error: 'forbidden' })
          else reply(200, await this.internal(decodeURIComponent(internal[1]), internal[2] as 'flush' | 'lock'))
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

  /** Django asks to save a document now (before submission) or to stop accepting edits (after it). */
  private async internal(documentName: string, action: 'flush' | 'lock') {
    const document = this.server.hocuspocus.documents.get(documentName)
    if (action === 'lock') {
      this.lock(documentName)
      return { status: 'locked', loaded: Boolean(document) }
    }
    if (!document) return { status: 'not_loaded' }
    const status = await this.store(documentName, document, null)
    return { status: status?.lastSave === 'failed' ? 'failed' : 'saved', error: status?.lastError ?? null }
  }

  statusOf(documentName: string): DocumentStatus | undefined {
    return this.status.get(documentName)
  }

  /** Materializes the document and hands state and rows to Django. */
  async store(documentName: string, document: Y.Doc, actorId: string | null): Promise<DocumentStatus | undefined> {
    const status = this.status.get(documentName)
    if (!status || status.locked || !this.options.store) return status
    let rows
    try {
      rows = materialize(document)
    } catch (error) {
      status.lastSave = 'failed'
      status.lastError = `materialize: ${(error as Error).message}`
      this.log('collab.materialize_failed', { document: documentName, error: status.lastError })
      await this.options.store.reportFailure(status.versionId, status.lastError).catch(() => undefined)
      return status
    }
    const result = await this.options.store.save(status.versionId, Y.encodeStateAsUpdate(document), rows, actorId)
    if (result.status === 'saved') {
      status.lastSave = 'saved'
      status.lastError = null
    } else if (result.status === 'locked') {
      this.lock(documentName)
    } else {
      status.lastSave = 'failed'
      status.lastError = result.error
      this.log('collab.save_failed', { document: documentName, error: result.error })
    }
    return status
  }

  /** No further edits are accepted: every open connection and every new one is read-only. */
  lock(documentName: string): void {
    const status = this.status.get(documentName)
    if (status) status.locked = true
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

  destroy() {
    return this.server.destroy()
  }
}

/** Kept for callers that only need a running server. */
export function createCollabServer(options: CollabServerOptions): CollabService {
  return new CollabService(options)
}
