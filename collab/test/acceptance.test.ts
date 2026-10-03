/**
 * Phase 3 completion check (spec 8.1 item 5) on the real collaboration
 * service over websockets: 2 to 5 clients edit an Arabic document at once,
 * one of them goes offline, keeps editing and comes back. Every client and
 * the server converge, the saved rows equal the live document and survive a
 * round trip through rows, a comment anchor stays on its text, and the
 * document reloads from the stored state with nothing lost.
 */
import {
  addBlock,
  addLink,
  addNode,
  blockFragment,
  blocksOf,
  createAnchor,
  deserializeAnchor,
  DocumentRuleError,
  hydrate,
  materialize,
  moveNode,
  nodesOf,
  renameNode,
  resolveAnchor,
  type Rows,
  serializeAnchor,
  setBlockContent,
  setBlockDeleted,
  setNodeDeleted,
  textsOf,
} from '@harak2/shared'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { CollabService } from '../src/server'
import { FakeStore } from './fakeStore'
import { type Client, connect, eventually, SECRET, settle, token } from './helpers'

const PORT = 12351
const LEVELS = 4
const SENTENCE = 'يصف المتدرب خطوات الإجراء الآمن بدقة'
const QUOTE = 'خطوات الإجراء'
const WORDS = ['المتدرب', 'يطبّق', 'إجراءات', 'السلامة', 'في', 'الموقع', '٣', '١٢', 'خطوات', '،', 'بدقة', 'الوحدة', 'التقييم', 'الكفاية', 'المهنيّة', 'مُعتمَد', '؟']
const ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩'

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

/** Deterministic pseudo-random numbers (mulberry32), one stream per client. */
function random(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const paragraph = (text: string) => ({ type: 'paragraph', content: [{ type: 'text', text }] })

/** The starting rows Django would hold: a root, two modules, Arabic blocks of each type. */
function seedRows(): Rows {
  const doc = new Y.Doc()
  const root = addNode(doc, { parent: null, title: 'برنامج السلامة المهنيّة', key: 'root' }, LEVELS)
  const first = addNode(doc, { parent: root, title: 'الوحدة الأولى: المخاطر', key: 'm1' }, LEVELS)
  const second = addNode(doc, { parent: root, title: 'الوحدة الثانية: الإسعافات', key: 'm2' }, LEVELS)
  addBlock(doc, { node_key: first, type: 'objective', key: 'anchored' })
  setBlockContent(doc, 'anchored', { type: 'doc', content: [paragraph('تمهيد قصير'), paragraph(SENTENCE)] })
  addBlock(doc, { node_key: first, type: 'content', key: 'c1' })
  setBlockContent(doc, 'c1', { type: 'doc', content: [paragraph('تُعرض المخاطر الشائعة في الموقع ٣ مع أمثلة')] })
  addBlock(doc, { node_key: second, type: 'assessment', key: 'a1' })
  setBlockContent(doc, 'a1', { type: 'doc', content: [paragraph('اختبار قصير من ١٠ أسئلة')] })
  addBlock(doc, { node_key: second, type: 'objective', key: 'o2' })
  setBlockContent(doc, 'o2', { type: 'doc', content: [paragraph('يُسعف المتدرب مصابًا وفق الخطوات')] })
  return materialize(doc)
}

/** Blocks nobody may delete or erase from: the commented one is only typed into, outside the quote. */
const KEPT_NODES = new Set(['root', 'm1'])

function editOnce(doc: Y.Doc, next: () => number, anchorKey: string, frozen: Set<string>) {
  const pick = <T>(items: T[]) => items[Math.floor(next() * items.length)]
  const word = () => pick(WORDS)
  const liveNodes = [...nodesOf(doc).entries()].filter(([, n]) => !n.get('deleted')).map(([k]) => k).sort()
  const liveBlocks = [...blocksOf(doc).entries()].filter(([, b]) => !b.get('deleted')).map(([k]) => k).sort()
  const kind = pick(['type', 'type', 'type', 'erase', 'node', 'block', 'move', 'rename', 'delete', 'link'])
  try {
    switch (kind) {
      case 'type': {
        const key = pick(liveBlocks.filter((k) => !frozen.has(k)))
        if (!key) return
        const text = pick(textsOf(blockFragment(doc, key)))
        if (!text) return
        let at = Math.floor(next() * (text.length + 1))
        if (key === anchorKey) {
          const here = resolveAnchor(doc, anchorOf.get(doc)!)
          if (here.text === text && at > here.from! && at < here.to!) at = next() < 0.5 ? here.from! : here.to!
        }
        text.insert(at, `${word()} `)
        break
      }
      case 'erase': {
        const key = pick(liveBlocks.filter((k) => k !== anchorKey && !frozen.has(k)))
        if (!key) return
        const text = pick(textsOf(blockFragment(doc, key)))
        if (!text || text.length < 3) return
        const from = Math.floor(next() * (text.length - 2))
        text.delete(from, 1 + Math.floor(next() * 2))
        break
      }
      case 'node':
        addNode(doc, { parent: pick(liveNodes), title: `${word()} ${word()}` }, LEVELS)
        break
      case 'block': {
        const key = addBlock(doc, { node_key: pick(liveNodes), type: pick(['objective', 'content', 'activity', 'assessment', 'reference'] as const) })
        setBlockContent(doc, key, { type: 'doc', content: [paragraph(`${word()} ${word()} ${word()}`)] })
        break
      }
      case 'move': {
        const movable = liveNodes.filter((k) => !KEPT_NODES.has(k) && k !== 'm2')
        if (movable.length) moveNode(doc, pick(movable), { parent: pick(liveNodes) }, LEVELS)
        break
      }
      case 'rename':
        renameNode(doc, pick(liveNodes), `${word()} ${word()}`)
        break
      case 'delete':
        if (next() < 0.5) {
          const key = pick(liveBlocks.filter((k) => k !== anchorKey && !frozen.has(k)))
          if (key) setBlockDeleted(doc, key, true)
        } else {
          const key = pick(liveNodes.filter((k) => !KEPT_NODES.has(k)))
          if (key) setNodeDeleted(doc, key, true)
        }
        break
      case 'link':
        if (liveBlocks.length > 1) addLink(doc, { kind: 'assessment_objective', source_key: pick(liveBlocks), target_key: pick(liveBlocks) })
        break
    }
  } catch (error) {
    if (!(error instanceof DocumentRuleError)) throw error
  }
}

const anchorOf = new WeakMap<Y.Doc, ReturnType<typeof createAnchor>>()
const json = (rows: Rows) => JSON.stringify(rows)
const body = (rows: Rows) => ({ nodes: rows.nodes, blocks: rows.blocks, links: rows.links })

describe('spec 8.1 item 5 on the collaboration service', () => {
  it.each([2, 3, 4, 5])('%i clients converge with Arabic content, one going offline and back, with nothing lost', async (size) => {
    const versionId = 500 + size
    const name = `program-version:${versionId}`
    store.seed(versionId, { rows: seedRows(), level_count: LEVELS })
    const clients: Client[] = []
    for (let i = 0; i < size; i += 1) {
      clients.push(await connect(PORT, name, await token({ sub: String(i + 1), ver: versionId, doc: name, name: `محرر ${i + 1}` })))
    }
    const serverDoc = () => service.server.hocuspocus.documents.get(name)!
    const converged = () => {
      const reference = json(materialize(serverDoc()))
      return clients.every((client) => json(materialize(client.doc)) === reference)
    }

    // A reviewer comments on a phrase; every client resolves the same anchor.
    const anchoredText = textsOf(blockFragment(clients[0].doc, 'anchored'))[1]
    const from = anchoredText.toString().indexOf(QUOTE)
    const stored = serializeAnchor(createAnchor('anchored', anchoredText, from, from + QUOTE.length))
    for (const client of clients) anchorOf.set(client.doc, deserializeAnchor(stored))

    // Each client adds one block with a marker nobody else may touch, to prove no edit is lost.
    const frozen = new Set<string>()
    const markers = clients.map((client, i) => {
      const marker = `إضافة المحرر رقم ${ARABIC_DIGITS[i + 1]}`
      const key = addBlock(client.doc, { node_key: 'm1', type: 'content', key: `marker-${i + 1}` })
      frozen.add(key)
      return { client, marker, key }
    })
    const streams = clients.map((_, i) => random(20261003 + 97 * size + i))

    // Round 1: everyone online.
    for (let step = 0; step < 15; step += 1) clients.forEach((client, i) => editOnce(client.doc, streams[i], 'anchored', frozen))
    await eventually(converged, 10_000)

    // Round 2: the last client loses its connection and keeps editing alone.
    const offline = clients[size - 1]
    const socket = offline.provider.configuration.websocketProvider
    socket.disconnect()
    await settle(200)
    for (let step = 0; step < 15; step += 1) clients.forEach((client, i) => editOnce(client.doc, streams[i], 'anchored', frozen))
    for (const { client, marker, key } of markers) setBlockContent(client.doc, key, { type: 'doc', content: [paragraph(marker)] })
    await settle(300)
    expect(json(materialize(offline.doc))).not.toBe(json(materialize(serverDoc())))

    // Round 3: it comes back while the others keep writing; edits on both sides merge.
    void socket.connect()
    for (let step = 0; step < 10; step += 1) clients.forEach((client, i) => editOnce(client.doc, streams[i], 'anchored', frozen))
    await eventually(converged, 15_000)

    const live = materialize(serverDoc())
    const text = JSON.stringify(live.blocks)
    for (const { marker } of markers) expect(text).toContain(marker)
    for (const client of clients) expect(resolveAnchor(client.doc, anchorOf.get(client.doc)!)).toMatchObject({ status: 'intact', current: QUOTE })

    // The service saved exactly the live document, and those rows survive a round trip.
    await eventually(() => json(store.saves.at(-1)?.rows ?? live) === json(live) && store.saves.length > 0, 5000)
    const saved = store.saves.at(-1)!.rows
    expect(json(saved)).toBe(json(live))
    expect(body(materialize(hydrate(saved)))).toEqual(body(saved))

    // Everyone leaves; the document reloads from the stored state, not the rows.
    for (const client of clients) client.provider.destroy()
    await eventually(() => !service.server.hocuspocus.documents.has(name), 10_000)
    store.documents.get(versionId)!.rows = null
    const reader = await connect(PORT, name, await token({ sub: '99', ver: versionId, doc: name, name: 'مراجع' }))
    expect(json(materialize(reader.doc))).toBe(json(saved))
    expect(resolveAnchor(reader.doc, deserializeAnchor(stored))).toMatchObject({ status: 'intact', current: QUOTE })
    reader.provider.destroy()
  })
})
