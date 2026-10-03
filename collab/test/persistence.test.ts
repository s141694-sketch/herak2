import { addBlock, addNode, blockFragment, hydrateStable, materialize, setBlockContent } from '@harak2/shared'
import { HocuspocusProvider, HocuspocusProviderWebsocket } from '@hocuspocus/provider'
import { Buffer } from 'node:buffer'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import WebSocket from 'ws'
import * as Y from 'yjs'

import { CollabService } from '../src/server'
import { FakeStore } from './fakeStore'
import { connect, eventually, SECRET, settle, token } from './helpers'

const PORT = 12341
let store: FakeStore
let service: CollabService

beforeEach(async () => {
  store = new FakeStore()
  service = new CollabService({
    port: PORT,
    tokenSecret: SECRET,
    store,
    debounceMs: 50,
    maxDebounceMs: 200,
    retryBaseMs: 50,
    retryMaxMs: 200,
    log: () => {},
  })
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
    store.nextSave = { status: 'failed', error: 'block x: content invalid', code: 'block_content_invalid', stateSaved: true, retryable: false }
    a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', 'تعديل'))
    await eventually(() => service.statusOf(NAME)?.lastSave === 'failed')
    expect(service.statusOf(NAME)?.lastError).toBe('block x: content invalid')
    const failed = JSON.stringify({ type: 'save-failed', error: 'block x: content invalid', code: 'block_content_invalid' })
    await eventually(() => a.stateless.includes(failed))
    // Someone who opens the document now learns about it too.
    const late = await connect(PORT, NAME, await token({ sub: '9' }))
    await eventually(() => late.stateless.includes(failed))
    late.provider.destroy()
    store.nextSave = { status: 'saved' }
    a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', 'إصلاح'))
    await eventually(() => a.stateless.includes(JSON.stringify({ type: 'saved' })))
    a.provider.destroy()
  })

  it('numbers its saves, so Django can drop a late older one', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    for (const title of ['١', '٢', '٣']) {
      a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', title))
      const before = store.saves.length
      await eventually(() => store.saves.length > before)
    }
    const seqs = store.saves.map((save) => save.seq)
    expect(seqs).toEqual([...seqs].sort((x, y) => x - y))
    expect(new Set(seqs).size).toBe(seqs.length)
    a.provider.destroy()
  })

  it('keeps a document whose save did not reach Django in memory, and retries until it does', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    store.nextSave = 'throw'
    a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', 'لم يُحفظ بعد'))
    await eventually(() => service.statusOf(NAME)?.lastSave === 'failed')
    expect(service.statusOf(NAME)?.lastErrorCode).toBe('save_unavailable')
    await eventually(() => a.stateless.some((m) => JSON.parse(m).code === 'save_unavailable'))
    a.provider.destroy()
    await settle(400)
    expect(service.server.hocuspocus.documents.has(NAME)).toBe(true)
    expect(store.attempts).toBeGreaterThan(1)
    store.nextSave = { status: 'saved' }
    await eventually(() => store.saves.length > 0, 3000)
    expect(store.saves.at(-1)!.rows.nodes[0].title).toBe('لم يُحفظ بعد')
    expect(store.saves.at(-1)!.actorId).toBe('7')
    await eventually(() => !service.server.hocuspocus.documents.has(NAME), 3000)
  })

  it('lets a document go once Django stored its state, even when its rows were refused', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    store.nextSave = { status: 'failed', error: 'node x: title', code: 'node_title_invalid', stateSaved: true, retryable: false }
    a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', 'عنوان'))
    await eventually(() => service.statusOf(NAME)?.lastSave === 'failed')
    a.provider.destroy()
    await eventually(() => !service.server.hocuspocus.documents.has(NAME), 3000)
    expect(store.attempts).toBe(1)
  })

  it('rebuilds the same rows into the same document every time, so an offline editor merges cleanly', async () => {
    const { rows, block } = rowsOfSample()
    store.seed(42, { rows })
    const first = await connect(PORT, NAME, await token({}))
    const loadedOnce = Y.encodeStateAsUpdate(service.server.hocuspocus.documents.get(NAME)!)
    const socket = first.provider.configuration.websocketProvider
    socket.disconnect()
    await eventually(() => !service.server.hocuspocus.documents.has(NAME), 5000)

    // Offline, the editor keeps typing into the copy it has.
    const text = (blockFragment(first.doc, block).get(0) as Y.XmlElement).get(0) as Y.XmlText
    text.insert(text.length, ' دون اتصال')

    const reader = await connect(PORT, NAME, await token({ sub: '8', mode: 'read' }))
    expect(Buffer.from(Y.encodeStateAsUpdate(service.server.hocuspocus.documents.get(NAME)!))).toEqual(Buffer.from(loadedOnce))
    void socket.connect()
    await eventually(() => JSON.stringify(materialize(reader.doc).blocks[0].content).includes('دون اتصال'), 5000)
    expect(materialize(reader.doc).blocks).toHaveLength(1)
    first.provider.destroy()
    reader.provider.destroy()
  })

  it('a lock that arrives while the document loads is kept', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    store.loadDelayMs = 300
    const opening = connect(PORT, NAME, await token({}))
    await settle(100)
    service.lock(NAME)
    const a = await opening
    expect(service.statusOf(NAME)?.locked).toBe(true)
    a.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', 'بعد القفل'))
    await settle()
    expect(store.saves).toEqual([])
    a.provider.destroy()
  })
})

describe('internal endpoints for Django', () => {
  const call = (path: string, secret = 'svc-secret-of-the-right-length-0123456789') =>
    fetch(`http://127.0.0.1:${PORT}${path}`, { method: 'POST', headers: { Authorization: `Service ${secret}` } })
  const answer = async (path: string) => (await (await call(path)).json()) as Record<string, any>

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
    expect((await call(`/internal/documents/${NAME}/freeze`, 'wrong')).status).toBe(403)
  })

  const titles = (client: { doc: Y.Doc }) => [...client.doc.getMap<Y.Map<unknown>>('nodes').values()].map((n) => n.get('title'))
  const rename = (client: { doc: Y.Doc }, title: string) =>
    client.doc.getMap<Y.Map<unknown>>('nodes').forEach((node) => node.set('title', title))

  it('freeze hands over the document as it stands and turns every editor read-only', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    const b = await connect(PORT, NAME, await token({ sub: '8' }))
    rename(a, 'قبل الإرسال')
    await eventually(() => titles(b).includes('قبل الإرسال'))
    const body = await answer(`/internal/documents/${NAME}/freeze`)
    expect(body.status).toBe('snapshot')
    expect(typeof body.token).toBe('string')
    expect(body.seq).toBeGreaterThan(0)
    expect(body.actor_id).toBe('7')
    expect(body.rows.nodes[0].title).toBe('قبل الإرسال')
    const copy = new Y.Doc()
    Y.applyUpdate(copy, Buffer.from(body.state, 'base64'))
    expect(materialize(copy).nodes[0].title).toBe('قبل الإرسال')
    expect(store.saves).toEqual([]) // Django stores the snapshot itself; nothing calls back into it.

    await eventually(() => a.stateless.includes(JSON.stringify({ type: 'frozen' })))
    rename(a, 'أثناء التجميد')
    await settle()
    expect(titles(b)).toEqual(['قبل الإرسال'])
    a.provider.destroy()
    b.provider.destroy()
  })

  it('unfreeze restores editing and recovers what was typed during the freeze', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    const b = await connect(PORT, NAME, await token({ sub: '8' }))
    const { token: freeze } = await answer(`/internal/documents/${NAME}/freeze`)
    await eventually(() => a.stateless.includes(JSON.stringify({ type: 'frozen' })))
    rename(a, 'كُتب أثناء التجميد')
    await settle()
    expect(titles(b)).toEqual(['البرنامج'])
    expect(await answer(`/internal/documents/${NAME}/unfreeze?token=${freeze}`)).toEqual({
      status: 'unfrozen',
      frozen: false,
    })
    await eventually(() => a.stateless.includes(JSON.stringify({ type: 'unfrozen' })))
    await eventually(() => titles(b).includes('كُتب أثناء التجميد'))
    rename(b, 'بعد التجميد')
    await eventually(() => titles(a).includes('بعد التجميد'))
    a.provider.destroy()
    b.provider.destroy()
  })

  it('stays frozen while another freeze holds it', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    const first = (await answer(`/internal/documents/${NAME}/freeze`)).token
    const second = (await answer(`/internal/documents/${NAME}/freeze`)).token
    expect(second).not.toBe(first)
    expect((await answer(`/internal/documents/${NAME}/unfreeze?token=${first}`)).frozen).toBe(true)
    expect(service.isFrozen(NAME)).toBe(true)
    expect((await answer(`/internal/documents/${NAME}/unfreeze?token=${second}`)).frozen).toBe(false)
    expect(service.isFrozen(NAME)).toBe(false)
    a.provider.destroy()
  })

  it('a document nobody has open is frozen from the moment it opens', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const body = await answer(`/internal/documents/${NAME}/freeze`)
    expect(body).toMatchObject({ status: 'not_loaded' })
    const a = await connect(PORT, NAME, await token({}))
    const b = await connect(PORT, NAME, await token({ sub: '8' }))
    rename(a, 'كُتب قبل فك التجميد')
    await settle()
    expect(titles(b)).toEqual(['البرنامج'])
    await call(`/internal/documents/${NAME}/unfreeze?token=${body.token}`)
    await eventually(() => titles(b).includes('كُتب قبل فك التجميد'))
    a.provider.destroy()
    b.provider.destroy()
  })

  it('edits made offline cannot slip into a frozen document when their editor comes back', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    const b = await connect(PORT, NAME, await token({ sub: '8' }))
    const socket = a.provider.configuration.websocketProvider
    socket.disconnect()
    await settle(100)
    rename(a, 'من دون اتصال')
    const { token: freeze } = await answer(`/internal/documents/${NAME}/freeze`)
    void socket.connect()
    await settle(400)
    expect(titles(b)).toEqual(['البرنامج'])
    await answer(`/internal/documents/${NAME}/unfreeze?token=${freeze}`)
    await eventually(() => titles(b).includes('من دون اتصال'))
    a.provider.destroy()
    b.provider.destroy()
  })

  it('edits typed while a locked version is still loading cannot slip in before the lock applies', async () => {
    const { rows } = rowsOfSample()
    store.seed(42, { rows, editable: false })
    store.loadDelayMs = 300
    // The editor's copy matches what the server will build, and it types while the server is still loading.
    const doc = hydrateStable(rows)
    const websocketProvider = new HocuspocusProviderWebsocket({ url: `ws://127.0.0.1:${PORT}`, WebSocketPolyfill: WebSocket })
    const provider = new HocuspocusProvider({ name: NAME, document: doc, token: await token({}), websocketProvider })
    provider.attach()
    await settle(100)
    rename({ doc }, 'أثناء التحميل')
    await eventually(() => service.server.hocuspocus.documents.has(NAME), 3000)
    await settle(200)
    expect(materialize(service.server.hocuspocus.documents.get(NAME)!).nodes[0].title).toBe('البرنامج')
    provider.destroy()
    websocketProvider.destroy()
  })

  it('lock ends every freeze, and a late unfreeze does not reopen the document', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    const b = await connect(PORT, NAME, await token({ sub: '8' }))
    const { token: freeze } = await answer(`/internal/documents/${NAME}/freeze`)
    expect(await answer(`/internal/documents/${NAME}/lock`)).toEqual({ status: 'locked', loaded: true })
    await eventually(() => b.stateless.includes(JSON.stringify({ type: 'locked' })))
    await call(`/internal/documents/${NAME}/unfreeze?token=${freeze}`)
    rename(a, 'بعد القفل')
    await settle()
    expect(titles(b)).toEqual(['البرنامج'])
    expect(b.stateless).not.toContain(JSON.stringify({ type: 'unfrozen' }))
    a.provider.destroy()
    b.provider.destroy()
  })

  it('a freeze nobody releases ends after a while, as Django says: editable again or locked', async () => {
    await service.destroy()
    service = new CollabService({
      port: PORT,
      tokenSecret: SECRET,
      serviceSecret: 'svc-secret-of-the-right-length-0123456789',
      store,
      debounceMs: 60_000,
      maxDebounceMs: 60_000,
      freezeTtlMs: 200,
      log: () => {},
    })
    await service.listen()
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    await call(`/internal/documents/${NAME}/freeze`)
    expect(service.isFrozen(NAME)).toBe(true)
    await eventually(() => a.stateless.includes(JSON.stringify({ type: 'unfrozen' })), 2000)
    expect(service.statusOf(NAME)?.locked).toBe(false)

    await call(`/internal/documents/${NAME}/freeze`)
    store.documents.get(42)!.editable = false
    await eventually(() => a.stateless.includes(JSON.stringify({ type: 'locked' })), 2000)
    expect(service.statusOf(NAME)?.locked).toBe(true)
    a.provider.destroy()

    // A document nobody has open has nothing to hold: its freeze just ends, without asking Django.
    const loads = store.loads
    await call('/internal/documents/program-version:77/freeze')
    expect(service.isFrozen('program-version:77')).toBe(true)
    await eventually(() => !service.isFrozen('program-version:77'), 2000)
    expect(store.loads).toBe(loads)
  })

  it('snapshot hands over the document without freezing it', async () => {
    store.seed(42, { rows: rowsOfSample().rows })
    const a = await connect(PORT, NAME, await token({}))
    rename(a, 'للمقارنة')
    await settle(100)
    const body = await answer(`/internal/documents/${NAME}/snapshot`)
    expect(body.status).toBe('snapshot')
    expect(body.token).toBeUndefined()
    expect(body.rows.nodes[0].title).toBe('للمقارنة')
    expect(service.isFrozen(NAME)).toBe(false)
    a.provider.destroy()
  })

  it('answers with the reason when the document cannot be turned into rows, instead of failing the call', async () => {
    const { rows, block } = rowsOfSample()
    store.seed(42, { rows })
    const a = await connect(PORT, NAME, await token({}))
    blockFragment(a.doc, block).insert(0, [new Y.XmlElement('image')])
    await settle(100)
    const response = await call(`/internal/documents/${NAME}/freeze`)
    expect(response.status).toBe(200)
    const body = (await response.json()) as Record<string, unknown>
    expect(body).toMatchObject({ status: 'failed', code: 'document_invalid' })
    expect(typeof body.token).toBe('string')
    expect((await call('/internal/documents/not-a-document/snapshot')).status).toBe(404)
    a.provider.destroy()
  })

  it('a snapshot of a document nobody has open says so', async () => {
    expect(await answer('/internal/documents/program-version:77/snapshot')).toEqual({ status: 'not_loaded' })
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
