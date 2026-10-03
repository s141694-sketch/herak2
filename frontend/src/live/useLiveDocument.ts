import { HocuspocusProvider } from '@hocuspocus/provider'
import { useEffect, useState } from 'react'
import * as Y from 'yjs'

import { http } from '../api'

export type LiveStatus = 'connecting' | 'connected' | 'disconnected'

export interface LiveDocument {
  doc: Y.Doc
  provider: HocuspocusProvider
  status: LiveStatus
  synced: boolean
  /** Stays true after the first sync, so content remains visible (read-only) while disconnected. */
  everSynced: boolean
  mode: 'read' | 'write' | null
  authFailed: boolean
  /** The version left draft status while this editor was open (it was submitted or cancelled). */
  locked: boolean
  /** Bumped when another client announces that comments changed. */
  commentsVersion: number
  /** Last save news from the service: an error, null once saving works again, undefined before any news. */
  saveError: string | null | undefined
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
      onStateless: ({ payload }) => {
        try {
          const type = JSON.parse(payload).type
          if (type === 'locked') update({ locked: true, mode: 'read' })
          if (type === 'save-failed') update({ saveError: String(JSON.parse(payload).error ?? '') })
          if (type === 'saved') update({ saveError: null })
          if (type === 'comments-changed') setLive((current) => (current && current.doc === doc ? { ...current, commentsVersion: current.commentsVersion + 1 } : current))
        } catch {
          // Ignore messages this client does not understand.
        }
      },
    })
    setLive({ doc, provider, status: 'connecting', synced: false, everSynced: false, mode: null, authFailed: false, locked: false, commentsVersion: 0, saveError: undefined })
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
