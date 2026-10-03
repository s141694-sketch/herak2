import { HocuspocusProvider } from '@hocuspocus/provider'
import { useEffect, useState } from 'react'
import * as Y from 'yjs'

import { http } from '../api'

export type LiveStatus = 'connecting' | 'connected' | 'disconnected'

/** Why a live save can fail, as the collaboration service and Django report it; each has a translation. */
export const SAVE_ERROR_CODES = [
  'rows_invalid',
  'node_too_deep',
  'node_title_invalid',
  'block_content_invalid',
  'document_invalid',
  'document_too_large',
  'save_unavailable',
  'save_refused',
] as const

export interface LiveDocument {
  doc: Y.Doc
  provider: HocuspocusProvider
  status: LiveStatus
  synced: boolean
  /** Stays true after the first sync, so content remains visible (read-only) while disconnected. */
  everSynced: boolean
  /** Local changes the service has not confirmed yet. */
  unsynced: number
  mode: 'read' | 'write' | null
  authFailed: boolean
  /** The version left draft status while this editor was open (it was submitted or cancelled). */
  locked: boolean
  /** Someone is submitting or cancelling the draft: edits wait until that ends (unfrozen) or locks it. */
  frozen: boolean
  /** Bumped when another client announces that comments changed. */
  commentsVersion: number
  /** Last save news from the service: an error, null once saving works again, undefined before any news. */
  saveError: string | null | undefined
  /** The code of the last save error, which the page translates. */
  saveErrorCode: string | null
}

interface TokenResponse {
  token: string
  document: string
  mode: 'read' | 'write'
}

export function collabUrl(): string {
  return `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/collab`
}

/**
 * Opens the live document of one version. A fresh short-lived token is fetched
 * on every (re)connection, so a reconnect after locking comes back read-only.
 */
export function useLiveDocument(versionId: number): LiveDocument | null {
  const [live, setLive] = useState<LiveDocument | null>(null)

  useEffect(() => {
    const doc = new Y.Doc()
    let mode: LiveDocument['mode'] = null
    const update = (patch: Partial<LiveDocument>) => setLive((current) => (current && current.doc === doc ? { ...current, ...patch } : current))
    const provider = new HocuspocusProvider({
      url: collabUrl(),
      name: `program-version:${versionId}`,
      document: doc,
      token: async () => {
        const response = await http.post<TokenResponse>(`/api/program-versions/${versionId}/collab-token/`)
        mode = response.mode
        update({ mode })
        return response.token
      },
      onStatus: ({ status }) => update({ status: status as LiveStatus, ...(status !== 'connected' ? { synced: false } : {}) }),
      onSynced: ({ state }) => update({ synced: state, mode, ...(state ? { everSynced: true } : {}) }),
      onAuthenticationFailed: () => update({ authFailed: true }),
      // A later attempt (a fresh token after a reconnect) may succeed: the failure notice goes with it.
      onAuthenticated: () => update({ authFailed: false }),
      onUnsyncedChanges: ({ number }) => update({ unsynced: number }),
      onStateless: ({ payload }) => {
        try {
          const message = JSON.parse(payload)
          const type = message.type
          if (type === 'locked') update({ locked: true, frozen: false, mode: 'read' })
          if (type === 'frozen') update({ frozen: true })
          if (type === 'unfrozen') {
            update({ frozen: false })
            // Anything typed in the moment before the freeze reached this editor was refused: send it again.
            provider.forceSync()
          }
          if (type === 'save-failed') update({ saveError: String(message.error ?? ''), saveErrorCode: message.code ? String(message.code) : null })
          if (type === 'saved') update({ saveError: null, saveErrorCode: null })
          if (type === 'comments-changed') setLive((current) => (current && current.doc === doc ? { ...current, commentsVersion: current.commentsVersion + 1 } : current))
        } catch {
          // Ignore messages this client does not understand.
        }
      },
    })
    setLive({ doc, provider, status: 'connecting', synced: false, everSynced: false, unsynced: 0, mode: null, authFailed: false, locked: false, frozen: false, commentsVersion: 0, saveError: undefined, saveErrorCode: null })
    return () => {
      provider.destroy()
      doc.destroy()
      setLive(null)
    }
  }, [versionId])

  return live
}

export function announceCommentsChanged(provider: HocuspocusProvider | undefined): void {
  provider?.sendStateless(JSON.stringify({ type: 'comments-changed' }))
}
