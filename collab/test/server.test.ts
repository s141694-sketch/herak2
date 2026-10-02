import { HocuspocusProvider, HocuspocusProviderWebsocket } from '@hocuspocus/provider'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import WebSocket from 'ws'
import * as Y from 'yjs'

import { createCollabServer } from '../src/server'

const PORT = 12340
let server: ReturnType<typeof createCollabServer>

beforeAll(async () => {
  server = createCollabServer({ port: PORT })
  await server.listen()
})

afterAll(async () => {
  await server.destroy()
})

function connect(name: string, document: Y.Doc): Promise<HocuspocusProvider> {
  return new Promise((resolve) => {
    const websocketProvider = new HocuspocusProviderWebsocket({ url: `ws://127.0.0.1:${PORT}`, WebSocketPolyfill: WebSocket })
    const provider = new HocuspocusProvider({ name, document, websocketProvider, onSynced: () => resolve(provider) })
    // With an externally supplied websocket provider the document provider must be attached explicitly.
    provider.attach()
  })
}

describe('collab service', () => {
  it('answers the health endpoint over HTTP', async () => {
    const response = await fetch(`http://127.0.0.1:${PORT}/health`)
    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ status: 'ok', service: 'collab' })
  })

  it('syncs two Yjs documents through the server', async () => {
    const a = new Y.Doc()
    const b = new Y.Doc()
    const name = `test-${Date.now()}`
    const pa = await connect(name, a)
    const pb = await connect(name, b)
    a.getText('t').insert(0, 'مرحبا')
    await new Promise<void>((resolve) => {
      const check = () => (b.getText('t').toString() === 'مرحبا' ? resolve() : setTimeout(check, 20))
      check()
    })
    expect(b.getText('t').toString()).toBe('مرحبا')
    pa.destroy()
    pb.destroy()
  })
})
