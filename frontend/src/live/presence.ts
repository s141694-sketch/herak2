import type { HocuspocusProvider } from '@hocuspocus/provider'
import { useEffect, useState } from 'react'

export interface Presence {
  clientId: number
  name: string
  color: string
  block: string | null
}

const COLORS = ['#7e1416', '#1e7a4c', '#2e3470', '#7a5b22', '#a0282c', '#3c6e8f']

export function colorFor(seed: string | number): string {
  let hash = 0
  for (const ch of String(seed)) hash = (hash * 31 + ch.codePointAt(0)!) >>> 0
  return COLORS[hash % COLORS.length]
}

/** Publishes who I am, and tracks who else is here and which block each person is editing. */
export function usePresence(provider: HocuspocusProvider | undefined, me: { id: number; name: string } | null): Presence[] {
  const [others, setOthers] = useState<Presence[]>([])

  useEffect(() => {
    const awareness = provider?.awareness
    if (!awareness || !me) return
    awareness.setLocalStateField('user', { name: me.name, color: colorFor(me.id) })
    const refresh = () => {
      const list: Presence[] = []
      awareness.getStates().forEach((state, clientId) => {
        if (clientId === awareness.clientID || !state.user) return
        list.push({ clientId, name: state.user.name, color: state.user.color, block: state.block ?? null })
      })
      setOthers(list.sort((a, b) => a.clientId - b.clientId))
    }
    refresh()
    awareness.on('change', refresh)
    return () => awareness.off('change', refresh)
  }, [provider, me])

  return others
}

export function announceBlock(provider: HocuspocusProvider | undefined, block: string | null): void {
  provider?.awareness?.setLocalStateField('block', block)
}
