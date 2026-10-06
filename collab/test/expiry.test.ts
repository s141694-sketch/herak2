import { HocuspocusProvider, HocuspocusProviderWebsocket } from '@hocuspocus/provider'
import WebSocket from 'ws'
import * as Y from 'yjs'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { createCollabServer } from '../src/server'
import { eventually, SECRET, settle, token } from './helpers'

// A live connection lasts only as long as its token, unless the page brings a fresh one: what the token
// stands for (the session, its organization, enforcement, the person's rights) is checked again by Django each
// time (from the independent review of phase 6).

const PORT = 12360
let server: ReturnType<typeof createCollabServer>

beforeAll(async () => {
  server = createCollabServer({ port: PORT, tokenSecret: SECRET, expiryGraceMs: 700 })  // token times are whole seconds: a fresh one may have only ms left
  await server.listen()
})

afterAll(async () => {
  await server.destroy()
})

interface Tracked {
  doc: Y.Doc
  provider: HocuspocusProvider
  closed: () => boolean
}

function open(tokenValue: string): Promise<Tracked> {
  return new Promise((resolve, reject) => {
    const doc = new Y.Doc()
    let closes = 0
    const websocketProvider = new HocuspocusProviderWebsocket({
      url: `ws://127.0.0.1:${PORT}`,
      WebSocketPolyfill: WebSocket,
      maxAttempts: 1,
    })
    const provider = new HocuspocusProvider({
      name: 'program-version:42',
      document: doc,
      token: tokenValue,
      websocketProvider,
      onSynced: () => resolve({ doc, provider, closed: () => closes > 0 }),
      onClose: () => {
        closes += 1
      },
      onAuthenticationFailed: ({ reason }) => reject(new Error(reason)),
    })
    provider.attach()
  })
}

const refresh = async (client: Tracked, claims: Record<string, unknown> = {}) =>
  client.provider.sendStateless(JSON.stringify({ type: 'refresh', token: await token(claims, { ttl: 1 }) }))

describe('live connections and their tokens', () => {
  it('closes a connection when its token runs out', async () => {
    const client = await open(await token({}, { ttl: 1 }))
    await eventually(client.closed, 3000)
    client.provider.destroy()
  })

  it('keeps a connection whose page brings fresh tokens', async () => {
    const client = await open(await token({}, { ttl: 1 }))
    const other = await open(await token({ sub: '8' }, { ttl: 60 }))
    for (let i = 0; i < 5; i += 1) {
      await refresh(client)
      await settle(400)
    }
    expect(client.closed()).toBe(false)
    client.doc.getText('t').insert(0, 'ما زال متصلًا')
    await eventually(() => other.doc.getText('t').toString() === 'ما زال متصلًا')
    client.provider.destroy()
    other.provider.destroy()
  })

  it.each([
    ['another person', { sub: '99' }],
    ['another document', { doc: 'program-version:43' }],
  ])('closes a connection whose fresh token is for %s', async (_label, claims) => {
    const client = await open(await token({}, { ttl: 60 }))
    await refresh(client, claims)
    await eventually(client.closed, 3000)
    client.provider.destroy()
  })

  it('makes a connection read-only when its fresh token only reads', async () => {
    const client = await open(await token({}, { ttl: 60 }))
    const other = await open(await token({ sub: '8' }, { ttl: 60 }))
    await refresh(client, { mode: 'read' })
    await settle()
    client.doc.getText('ro').insert(0, 'لا يصل')
    await settle()
    expect(other.doc.getText('ro').toString()).toBe('')
    client.provider.destroy()
    other.provider.destroy()
  })
})
