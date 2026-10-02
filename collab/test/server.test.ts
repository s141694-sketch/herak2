import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { createCollabServer } from '../src/server'
import { connect, eventually, SECRET, settle, token } from './helpers'

const PORT = 12340
let server: ReturnType<typeof createCollabServer>

beforeAll(async () => {
  server = createCollabServer({ port: PORT, tokenSecret: SECRET })
  await server.listen()
})

afterAll(async () => {
  await server.destroy()
})

describe('collab service', () => {
  it('answers the health endpoint over HTTP', async () => {
    const response = await fetch(`http://127.0.0.1:${PORT}/health`)
    expect(await response.json()).toEqual({ status: 'ok', service: 'collab' })
  })

  it('syncs two writers holding valid tokens for the document', async () => {
    const a = await connect(PORT, 'program-version:42', await token({}))
    const b = await connect(PORT, 'program-version:42', await token({ sub: '8' }))
    a.doc.getText('t').insert(0, 'مرحبا')
    await eventually(() => b.doc.getText('t').toString() === 'مرحبا')
    a.provider.destroy()
    b.provider.destroy()
  })

  it.each([
    ['a token for another document', () => token({ doc: 'program-version:43' })],
    ['an expired token', () => token({}, { ttl: -10 })],
    ['a token signed with another secret', () => token({}, { secret: 'another-secret-of-the-right-length-0123' })],
    ['no token', async () => ''],
  ])('refuses %s', async (_label, make) => {
    await expect(connect(PORT, 'program-version:42', await make())).rejects.toThrow()
  })

  it('opens read grants read-only: their edits reach nobody', async () => {
    const writer = await connect(PORT, 'program-version:42', await token({}))
    const reader = await connect(PORT, 'program-version:42', await token({ sub: '9', mode: 'read' }))
    writer.doc.getText('ro').insert(0, 'من الكاتب')
    await eventually(() => reader.doc.getText('ro').toString() === 'من الكاتب')
    reader.doc.getText('ro').insert(0, 'من القارئ ')
    await settle()
    expect(writer.doc.getText('ro').toString()).toBe('من الكاتب')
    writer.provider.destroy()
    reader.provider.destroy()
  })
})
