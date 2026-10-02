import fc from 'fast-check'
import { describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { materialize } from '../src/materialize'
import { addBlock, addLink, addNode, DocumentRuleError, moveNode, setBlockDeleted, setNodeDeleted } from '../src/operations'
import { blockFragment, blocksOf, nodesOf } from '../src/schema'
import { textArb } from './arbitraries'

const SEED = Number(process.env.SHARED_SEED ?? 20261003)
const RUNS = Number(process.env.SHARED_SIM_RUNS ?? 300)
const LEVELS = 5

interface Client {
  doc: Y.Doc
  pending: Map<number, Uint8Array[]>
}

function cluster(size: number, ids: number[], seed: Y.Doc): Client[] {
  const snapshot = Y.encodeStateAsUpdate(seed)
  const clients: Client[] = []
  for (let i = 0; i < size; i += 1) {
    const doc = new Y.Doc()
    doc.clientID = ids[i]
    Y.applyUpdate(doc, snapshot)
    const client: Client = { doc, pending: new Map() }
    doc.on('update', (update: Uint8Array, origin: unknown) => {
      if (origin === 'net') return
      clients.forEach((_, j) => j !== i && (client.pending.get(j) ?? client.pending.set(j, []).get(j)!).push(update))
    })
    clients.push(client)
  }
  return clients
}

function deliver(from: Client, toIndex: number, to: Client) {
  const queue = (from.pending.get(toIndex) ?? []).reverse()
  from.pending.set(toIndex, [])
  for (const update of queue) Y.applyUpdate(to.doc, update, 'net')
}

function syncAll(clients: Client[]) {
  for (let round = 0; round < 2; round += 1)
    for (const a of clients) for (const b of clients) if (a !== b) Y.applyUpdate(b.doc, Y.encodeStateAsUpdate(a.doc, Y.encodeStateVector(b.doc)), 'net')
}

function texts(doc: Y.Doc, key: string): Y.XmlText[] {
  const found: Y.XmlText[] = []
  const walk = (n: Y.XmlFragment | Y.XmlElement) => n.toArray().forEach((c) => (c instanceof Y.XmlText ? found.push(c) : c instanceof Y.XmlElement && walk(c)))
  walk(blockFragment(doc, key))
  return found
}

const op = fc.record({
  client: fc.nat({ max: 4 }),
  kind: fc.constantFrom('node', 'block', 'type', 'erase', 'move', 'delete', 'link'),
  a: fc.nat({ max: 1000 }),
  b: fc.nat({ max: 1000 }),
  text: textArb,
})

function apply(doc: Y.Doc, o: { kind: string; a: number; b: number; text: string }) {
  const nodes = [...nodesOf(doc).keys()].sort()
  const blocks = [...blocksOf(doc).keys()].sort()
  try {
    switch (o.kind) {
      case 'node':
        addNode(doc, { parent: o.a % 4 === 0 || !nodes.length ? null : nodes[o.a % nodes.length], title: o.text }, LEVELS)
        break
      case 'block':
        if (nodes.length) {
          const key = addBlock(doc, { node_key: nodes[o.a % nodes.length], type: (['objective', 'content', 'assessment'] as const)[o.b % 3] })
          const p = new Y.XmlElement('paragraph')
          p.insert(0, [new Y.XmlText(o.text)])
          blockFragment(doc, key).insert(0, [p])
        }
        break
      case 'type':
        if (blocks.length) {
          const ts = texts(doc, blocks[o.a % blocks.length])
          if (ts.length) {
            const t = ts[o.b % ts.length]
            let at = o.b % (t.length + 1)
            const s = t.toString()
            if (at > 0 && at < s.length && s.charCodeAt(at) >= 0xdc00 && s.charCodeAt(at) <= 0xdfff) at -= 1
            t.insert(at, o.text)
          }
        }
        break
      case 'erase':
        if (blocks.length) {
          const ts = texts(doc, blocks[o.a % blocks.length])
          const t = ts[o.b % Math.max(ts.length, 1)]
          const s = t?.toString() ?? ''
          if (s.length > 2) {
            let from = o.b % (s.length - 1)
            if (s.charCodeAt(from) >= 0xdc00 && s.charCodeAt(from) <= 0xdfff) from -= 1
            let to = Math.min(s.length, from + 2)
            if (to < s.length && s.charCodeAt(to) >= 0xdc00 && s.charCodeAt(to) <= 0xdfff) to += 1
            t!.delete(from, to - from)
          }
        }
        break
      case 'move':
        if (nodes.length) moveNode(doc, nodes[o.a % nodes.length], { parent: o.b % 4 === 0 ? null : nodes[o.b % nodes.length] }, LEVELS)
        break
      case 'delete':
        if (o.b % 2 && blocks.length) setBlockDeleted(doc, blocks[o.a % blocks.length], true)
        else if (nodes.length) setNodeDeleted(doc, nodes[o.a % nodes.length], true)
        break
      case 'link':
        if (blocks.length > 1) addLink(doc, { kind: 'assessment_objective', source_key: blocks[o.a % blocks.length], target_key: blocks[o.b % blocks.length] })
        break
    }
  } catch (error) {
    if (!(error instanceof DocumentRuleError)) throw error
  }
}

describe('3-5 concurrent clients', () => {
  it('concurrent moves forming a cycle converge to the same repaired tree', () => {
    const seed = new Y.Doc()
    const root = addNode(seed, { parent: null, title: 'r', key: 'r' }, LEVELS)
    addNode(seed, { parent: root, title: 'a', key: 'a' }, LEVELS)
    addNode(seed, { parent: root, title: 'b', key: 'b' }, LEVELS)
    const [c1, c2, c3] = cluster(3, [11, 22, 33], seed)
    moveNode(c1.doc, 'a', { parent: 'b' }, LEVELS)
    moveNode(c2.doc, 'b', { parent: 'a' }, LEVELS)
    syncAll([c1, c2, c3])
    const rows = materialize(c1.doc)
    expect(rows.issues).toEqual([{ kind: 'cycle', keys: ['a', 'b'] }])
    expect(materialize(c2.doc)).toEqual(rows)
    expect(materialize(c3.doc)).toEqual(rows)
  })

  it(`${RUNS} random sessions converge and materialize identically`, () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 3, max: 5 }),
        fc.uniqueArray(fc.integer({ min: 1, max: 1_000_000 }), { minLength: 5, maxLength: 5 }),
        fc.array(op, { minLength: 20, maxLength: 80 }),
        fc.array(fc.tuple(fc.nat({ max: 4 }), fc.nat({ max: 4 })), { maxLength: 20 }),
        (size, ids, ops, syncs) => {
          const seed = new Y.Doc()
          addNode(seed, { parent: null, title: 'جذر', key: 'root' }, LEVELS)
          const clients = cluster(size, ids, seed)
          ops.forEach((o, i) => {
            apply(clients[o.client % size].doc, o)
            if (i % 5 === 4 && syncs.length) {
              const [f, t] = syncs.shift()!
              if (f % size !== t % size) deliver(clients[f % size], t % size, clients[t % size])
            }
          })
          syncAll(clients)
          const reference = materialize(clients[0].doc)
          for (const client of clients.slice(1)) expect(materialize(client.doc)).toEqual(reference)
        },
      ),
      { seed: SEED, numRuns: RUNS },
    )
  })
})
