import { HocuspocusProvider, HocuspocusProviderWebsocket } from '@hocuspocus/provider'
import { SignJWT } from 'jose'
import WebSocket from 'ws'
import * as Y from 'yjs'

export const SECRET = 'test-collab-token-secret-0123456789'

export async function token(claims: Record<string, unknown>, options: { secret?: string; ttl?: number } = {}) {
  const now = Math.floor(Date.now() / 1000)
  return new SignJWT({ sub: '7', org: 1, ver: 42, doc: 'program-version:42', mode: 'write', name: 'مازن', ...claims })
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuer('harak2-api')
    .setAudience('harak2-collab')
    .setIssuedAt(now)
    .setExpirationTime(now + (options.ttl ?? 120))
    .sign(new TextEncoder().encode(options.secret ?? SECRET))
}

export interface Client {
  doc: Y.Doc
  provider: HocuspocusProvider
  stateless: string[]
}

/** Connects and resolves once synced, or rejects when authentication fails. */
export function connect(port: number, name: string, tokenValue: string): Promise<Client> {
  return new Promise((resolve, reject) => {
    const doc = new Y.Doc()
    const stateless: string[] = []
    const websocketProvider = new HocuspocusProviderWebsocket({ url: `ws://127.0.0.1:${port}`, WebSocketPolyfill: WebSocket })
    const provider = new HocuspocusProvider({
      name,
      document: doc,
      token: tokenValue,
      websocketProvider,
      onSynced: () => resolve({ doc, provider, stateless }),
      onStateless: ({ payload }) => stateless.push(payload),
      onAuthenticationFailed: ({ reason }) => {
        provider.destroy()
        websocketProvider.destroy()
        reject(new Error(reason))
      },
    })
    provider.attach()
  })
}

export async function eventually(check: () => boolean, timeoutMs = 3000) {
  const started = Date.now()
  while (!check()) {
    if (Date.now() - started > timeoutMs) throw new Error('condition not met in time')
    await new Promise((r) => setTimeout(r, 20))
  }
}

export const settle = (ms = 300) => new Promise((r) => setTimeout(r, ms))
