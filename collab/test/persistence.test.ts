import { addBlock, addNode, blockFragment, materialize, setBlockContent } from '@harak2/shared'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { CollabService } from '../src/server'
import { FakeStore } from './fakeStore'
import { connect, eventually, SECRET, settle, token } from './helpers'

const PORT = 12341
let store: FakeStore
let service: CollabService

beforeEach(async () => {
  store = new FakeStore()
  service = new CollabService({ port: PORT, tokenSecret: SECRET, store, debounceMs: 50, maxDebounceMs: 200, log: () => {} })
  await service.listen()
})

afterEach(async () => {
  await service.destroy()
})

const NAME = 'program-version:42'

function rowsOfSample() {
  const doc = new Y.Doc()
  const root = addNode(doc, { parent: null, title: 'البرنامج' }, 4)
  const block = addBlock(doc, { node_key: root, type: 'objective' })
  setBlockContent(doc, block, { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'يصف المتدرب الإجراء' }] }] })
  return { rows: materialize(doc), block }
}

describe('loading and saving through Django', () => {
  it('builds a document from rows when Django has no state yet, then saves state and rows after an edit', async () => {
    const { rows, block } = rowsOfSample()
    store.seed(42, { rows })
    const client = await connect(PORT, NAME, await token({}))
    expect(materialize(client.doc).blocks[0].content).toEqual(rows.blocks[0].content)

    const text = (blockFragment(client.doc, block).get(0) as Y.XmlElement).get(0) as Y.XmlText
    text.insert(text.length, ' بدقة')
    await eventually(() => store.saves.length > 0)
    const saved = store.saves.at(-1)!
    expect(saved.actorId).toBe('7')
    expect(JSON.stringify(saved.rows.blocks[0].content)).toContain('يصف المتدرب الإجراء بدقة')
    expect(store.documents.get(42)!.state).not.toBeNull()
    client.provider.destroy()
  })

  it('reloads from the stored state after the document is unloaded', async () => {
    const { rows, block } = rowsOfSample()
    store.seed(42, { rows })
    const first = await connect(PORT, NAME, await token({}))
    const text = (blockFragment(first.doc, block).get(0) as Y.XmlElement).get(0) as Y.XmlText
    text.insert(0, 'أولًا: ')
    await eventually(() => store.saves.length > 0)
    first.provider.destroy()
    await eventually(() => !service.server.hocuspocus.documents.has(NAME), 5000)

    store.documents.get(42)!.rows = null
    const second = await connect(PORT, NAME, await token({ sub: '8' }))
    expect(JSON.stringify(materialize(second.doc).blocks[0].content)).toContain('أولًا: يصف')
    second.provider.destroy()
  })

  it('locks the document when Django says the version is locked: later edits reach nobody', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    const b = await connect(PORT, NAME, await token({ sub: '8' }))
    store.nextSave = { status: 'locked' }
    a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', 'تعديل قبل القفل'))
    await eventually(() => service.statusOf(NAME)?.locked === true)
    a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', 'بعد القفل'))
    await settle()
    const titles = [...b.doc.getMap<Y.Map<unknown>>('nodes').values()].map((n) => n.get('title'))
    expect(titles).not.toContain('بعد القفل')
    a.provider.destroy()
    b.provider.destroy()
  })

  it('opens a locked version read-only from the start', async () => {
    store.seed(42, { rows: rowsOfSample().rows, editable: false })
    const a = await connect(PORT, NAME, await token({}))
    const b = await connect(PORT, NAME, await token({ sub: '8' }))
    a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', 'لن يصل'))
    await settle()
    expect([...b.doc.getMap<Y.Map<unknown>>('nodes').values()].map((n) => n.get('title'))).toEqual(['البرنامج'])
    expect(store.saves).toEqual([])
    a.provider.destroy()
    b.provider.destroy()
  })

  it('records a failed save without losing the live document', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    store.nextSave = { status: 'failed', error: 'block x: content invalid' }
    a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', 'تعديل'))
    await eventually(() => service.statusOf(NAME)?.lastSave === 'failed')
    expect(service.statusOf(NAME)?.lastError).toBe('block x: content invalid')
    await eventually(() => a.stateless.includes(JSON.stringify({ type: 'save-failed', error: 'block x: content invalid' })))
    store.nextSave = { status: 'saved' }
    a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', 'إصلاح'))
    await eventually(() => a.stateless.includes(JSON.stringify({ type: 'saved' })))
    a.provider.destroy()
  })
})

describe('internal endpoints for Django', () => {
  const call = (path: string, secret = 'svc-secret-of-the-right-length-0123456789') =>
    fetch(`http://127.0.0.1:${PORT}${path}`, { method: 'POST', headers: { Authorization: `Service ${secret}` } })

  beforeEach(async () => {
    await service.destroy()
    service = new CollabService({
      port: PORT,
      tokenSecret: SECRET,
      serviceSecret: 'svc-secret-of-the-right-length-0123456789',
      store,
      debounceMs: 60_000,
      maxDebounceMs: 60_000,
      log: () => {},
    })
    await service.listen()
  })

  it('refuses callers without the service secret', async () => {
    expect((await call(`/internal/documents/${NAME}/flush`, 'wrong')).status).toBe(403)
  })

  it('flush saves pending edits right away, without waiting for the debounce', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', 'قبل الإرسال'))
    await settle(100)
    expect(store.saves).toEqual([])
    const body = await (await call(`/internal/documents/${NAME}/flush`)).json()
    expect(body).toEqual({ status: 'saved', error: null })
    expect(store.saves.at(-1)!.rows.nodes[0].title).toBe('قبل الإرسال')
    a.provider.destroy()
  })

  it('flush of a document nobody has open is a no-op', async () => {
    expect(await (await call('/internal/documents/program-version:77/flush')).json()).toEqual({ status: 'not_loaded' })
  })

  it('lock turns every connection read-only', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    const b = await connect(PORT, NAME, await token({ sub: '8' }))
    expect(await (await call(`/internal/documents/${NAME}/lock`)).json()).toEqual({ status: 'locked', loaded: true })
    await eventually(() => b.stateless.includes(JSON.stringify({ type: 'locked' })))
    a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', 'بعد القفل'))
    await settle()
    expect([...b.doc.getMap<Y.Map<unknown>>('nodes').values()].map((n) => n.get('title'))).toEqual(['البرنامج'])
    a.provider.destroy()
    b.provider.destroy()
  })
})


describe('relaying announcements', () => {
  it('passes a comments-changed announcement to the other clients only', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    const b = await connect(PORT, NAME, await token({ sub: '8', mode: 'read' }))
    a.provider.sendStateless(JSON.stringify({ type: 'comments-changed' }))
    await eventually(() => b.stateless.includes(JSON.stringify({ type: 'comments-changed' })))
    await settle(100)
    expect(a.stateless).not.toContain(JSON.stringify({ type: 'comments-changed' }))
    a.provider.destroy()
    b.provider.destroy()
  })
})
