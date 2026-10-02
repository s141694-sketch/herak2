import fc from 'fast-check'
import * as Y from 'yjs'

import { setBlockContent } from '../src/materialize'
import { BLOCK_TYPES, blocksMap, createBlock, createNode, isSelfOrDescendant, moveNode, nodesMap, softDeleteBlock, softDeleteNode } from '../src/schema'
import { textArb } from './arbitraries'

/** A simulated Yjs client with an outbox of updates not yet delivered to every peer. */
export interface Client {
  id: number
  doc: Y.Doc
  /** Updates produced locally, keyed by the peer they still have to reach. */
  outbox: Map<number, Uint8Array[]>
}

export function newCluster(size: number, seed: Y.Doc, clientIds?: number[]): Client[] {
  const snapshot = Y.encodeStateAsUpdate(seed)
  const clients: Client[] = []
  for (let id = 0; id < size; id += 1) {
    const doc = new Y.Doc()
    if (clientIds) doc.clientID = clientIds[id]
    Y.applyUpdate(doc, snapshot)
    const client: Client = { id, doc, outbox: new Map() }
    doc.on('update', (update: Uint8Array, origin: unknown) => {
      if (origin === 'network') return
      for (const peer of clients) {
        if (peer.id === id) continue
        if (!client.outbox.has(peer.id)) client.outbox.set(peer.id, [])
        client.outbox.get(peer.id)!.push(update)
      }
    })
    clients.push(client)
  }
  return clients
}

/** Delivers the pending updates from `from` to `to`, shuffled, to mimic reordering. */
export function partialSync(from: Client, to: Client): void {
  if (from === to) return
  const pending = from.outbox.get(to.id) ?? []
  from.outbox.set(to.id, [])
  for (let i = pending.length - 1; i > 0; i -= 1) {
    const j = (i * 7919) % (i + 1)
    ;[pending[i], pending[j]] = [pending[j], pending[i]]
  }
  Y.transact(to.doc, () => {
    for (const update of pending) Y.applyUpdate(to.doc, update)
  }, 'network')
}

/** Exchanges full state between every pair until all state vectors agree. */
export function fullSync(clients: Client[]): void {
  for (const client of clients) client.outbox.clear()
  for (let round = 0; round < 3; round += 1) {
    for (const a of clients) {
      for (const b of clients) {
        if (a === b) continue
        const missing = Y.encodeStateAsUpdate(a.doc, Y.encodeStateVector(b.doc))
        Y.applyUpdate(b.doc, missing, 'network')
      }
    }
  }
  const vectors = clients.map((c) => Buffer.from(Y.encodeStateVector(c.doc)).toString('hex'))
  if (new Set(vectors).size !== 1) throw new Error('state vectors differ after full sync')
}

export type SimOp =
  | { kind: 'insertNode'; client: number; pick: number; order: number }
  | { kind: 'insertBlock'; client: number; pick: number; type: number; text: string }
  | { kind: 'insertText'; client: number; pick: number; index: number; text: string }
  | { kind: 'deleteText'; client: number; pick: number; index: number; length: number }
  | { kind: 'moveNode'; client: number; pick: number; target: number; order: number }
  | { kind: 'deleteNode'; client: number; pick: number }
  | { kind: 'deleteBlock'; client: number; pick: number }

const client = fc.nat({ max: 4 })
const pick = fc.nat({ max: 1000 })

export const opArb: fc.Arbitrary<SimOp> = fc.oneof(
  { weight: 3, arbitrary: fc.record({ kind: fc.constant('insertNode' as const), client, pick, order: fc.integer({ min: -3, max: 6 }) }) },
  { weight: 3, arbitrary: fc.record({ kind: fc.constant('insertBlock' as const), client, pick, type: fc.nat({ max: 4 }), text: textArb }) },
  { weight: 6, arbitrary: fc.record({ kind: fc.constant('insertText' as const), client, pick, index: pick, text: textArb }) },
  { weight: 3, arbitrary: fc.record({ kind: fc.constant('deleteText' as const), client, pick, index: pick, length: fc.integer({ min: 1, max: 6 }) }) },
  { weight: 3, arbitrary: fc.record({ kind: fc.constant('moveNode' as const), client, pick, target: pick, order: fc.integer({ min: -3, max: 6 }) }) },
  { weight: 1, arbitrary: fc.record({ kind: fc.constant('deleteNode' as const), client, pick }) },
  { weight: 1, arbitrary: fc.record({ kind: fc.constant('deleteBlock' as const), client, pick }) },
)

let keyCounter = 0

function nodeKeys(doc: Y.Doc): string[] {
  return [...nodesMap(doc).keys()].sort()
}

function blockKeys(doc: Y.Doc): string[] {
  return [...blocksMap(doc).keys()].sort()
}

function allTexts(doc: Y.Doc, blockKey: string): Y.XmlText[] {
  const out: Y.XmlText[] = []
  const walk = (node: Y.XmlFragment | Y.XmlElement) => {
    for (const child of node.toArray()) {
      if (child instanceof Y.XmlText) out.push(child)
      else if (child instanceof Y.XmlElement) walk(child)
    }
  }
  walk(blocksMap(doc).get(blockKey)!.get('content') as Y.XmlFragment)
  return out
}

/** Avoids splitting a surrogate pair, as a real editor caret never sits between one. */
function safeIndex(text: string, index: number): number {
  let i = index % (text.length + 1)
  if (i > 0 && i < text.length && text.charCodeAt(i) >= 0xdc00 && text.charCodeAt(i) <= 0xdfff) i -= 1
  return i
}

export function applyOp(c: Client, op: SimOp): void {
  const doc = c.doc
  const nodes = nodeKeys(doc)
  switch (op.kind) {
    case 'insertNode': {
      const parent = op.pick % 4 === 0 ? null : nodes[op.pick % nodes.length]
      createNode(doc, `c${c.id}-n${keyCounter++}`, { parent, order: op.order })
      return
    }
    case 'insertBlock': {
      const key = `c${c.id}-b${keyCounter++}`
      createBlock(doc, key, { node_key: nodes[op.pick % nodes.length], type: BLOCK_TYPES[op.type % BLOCK_TYPES.length] })
      setBlockContent(doc, key, { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: op.text }] }] })
      return
    }
    case 'insertText': {
      const blocks = blockKeys(doc)
      if (!blocks.length) return
      const texts = allTexts(doc, blocks[op.pick % blocks.length])
      if (!texts.length) return
      const text = texts[op.index % texts.length]
      text.insert(safeIndex(text.toString(), op.index), op.text)
      return
    }
    case 'deleteText': {
      const blocks = blockKeys(doc)
      if (!blocks.length) return
      const texts = allTexts(doc, blocks[op.pick % blocks.length])
      if (!texts.length) return
      const text = texts[op.index % texts.length]
      const current = text.toString()
      if (!current.length) return
      const start = safeIndex(current, op.index)
      const end = safeIndex(current, Math.min(current.length, start + op.length))
      if (end > start) text.delete(start, end - start)
      return
    }
    case 'moveNode': {
      const key = nodes[op.pick % nodes.length]
      const target = op.target % 4 === 0 ? null : nodes[op.target % nodes.length]
      if (isSelfOrDescendant(doc, key, target)) return
      moveNode(doc, key, { parent: target, order: op.order })
      return
    }
    case 'deleteNode':
      softDeleteNode(doc, nodes[op.pick % nodes.length])
      return
    case 'deleteBlock': {
      const blocks = blockKeys(doc)
      if (blocks.length) softDeleteBlock(doc, blocks[op.pick % blocks.length])
      return
    }
  }
}
