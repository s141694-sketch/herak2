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
  mode: 'read' | 'write' | null
  authFailed: boolean
  /** The version left draft status while this editor was open (it was submitted or cancelled). */
  locked: boolean
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
      onSynced: ({ state }) => update({ synced: state, mode }),
      onAuthenticationFailed: () => update({ authFailed: true }),
      onStateless: ({ payload }) => {
        try {
          if (JSON.parse(payload).type === 'locked') update({ locked: true, mode: 'read' })
        } catch {
          // Ignore messages this client does not understand.
        }
      },
    })
    setLive({ doc, provider, status: 'connecting', synced: false, mode: null, authFailed: false, locked: false })
    return () => {
      provider.destroy()
      doc.destroy()
      setLive(null)
    }
  }, [versionId])

  return live
}
