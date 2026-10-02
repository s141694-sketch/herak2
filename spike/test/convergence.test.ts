import fc from 'fast-check'
import { describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { materialize, setBlockContent } from '../src/materialize'
import { blockFragment, createBlock, createNode, moveNode, nodesMap } from '../src/schema'
import { structureArb } from './arbitraries'
import { buildDoc } from './roundtrip.property.test'
import { applyOp, type Client, fullSync, newCluster, opArb, partialSync, type SimOp } from './simulation'

const SEED = Number(process.env.SPIKE_SEED ?? 20261003)
const NUM_RUNS = Number(process.env.SPIKE_SIM_RUNS ?? 300)

function expectConverged(clients: Client[]) {
  const reference = materialize(clients[0].doc)
  for (const client of clients.slice(1)) {
    expect(materialize(client.doc)).toEqual(reference)
    for (const block of reference.blocks) {
      expect(blockFragment(client.doc, block.block_key).toString()).toBe(blockFragment(clients[0].doc, block.block_key).toString())
    }
  }
  return reference
}

describe('multi-client convergence (task 0.5)', () => {
  it('concurrent moves that form a cycle converge to the same repaired tree on every client', () => {
    const seed = new Y.Doc()
    createNode(seed, 'root', { parent: null, order: 0 })
    createNode(seed, 'a', { parent: 'root', order: 0 })
    createNode(seed, 'b', { parent: 'root', order: 1 })
    const clients = newCluster(3, seed)

    // Offline: client 0 moves a under b, client 1 moves b under a. Both are legal locally.
    moveNode(clients[0].doc, 'a', { parent: 'b', order: 0 })
    moveNode(clients[1].doc, 'b', { parent: 'a', order: 0 })
    fullSync(clients)

    const rows = expectConverged(clients)
    expect(rows.issues).toEqual([{ kind: 'cycle', node_keys: ['a', 'b'], detail: 'cycle broken at a' }])
    expect(rows.nodes.map((n) => [n.node_key, n.parent_key])).toEqual([
      ['a', null],
      ['b', 'a'],
      ['root', null],
    ])
  })

  it('a node moved under a parent that another client deleted keeps its parent link', () => {
    const seed = new Y.Doc()
    createNode(seed, 'root', { parent: null, order: 0 })
    createNode(seed, 'a', { parent: 'root', order: 0 })
    createNode(seed, 'b', { parent: 'root', order: 1 })
    const clients = newCluster(2, seed)
    moveNode(clients[0].doc, 'a', { parent: 'b', order: 0 })
    nodesMap(clients[1].doc).get('b')!.set('deleted', true)
    fullSync(clients)
    const rows = expectConverged(clients)
    expect(rows.issues).toEqual([])
    expect(rows.nodes.find((n) => n.node_key === 'a')).toMatchObject({ parent_key: 'b', deleted: false })
    expect(rows.nodes.find((n) => n.node_key === 'b')).toMatchObject({ deleted: true })
  })

  it('concurrent Arabic text edits in the same block converge', () => {
    const seed = new Y.Doc()
    createNode(seed, 'root', { parent: null, order: 0 })
    createBlock(seed, 'b1', { node_key: 'root', type: 'objective' })
    setBlockContent(seed, 'b1', { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'يصف المتدرب الإجراء' }] }] })
    const clients = newCluster(3, seed)

    const textOf = (c: Client) => (blockFragment(c.doc, 'b1').get(0) as Y.XmlElement).get(0) as Y.XmlText
    textOf(clients[0]).insert(4, 'خطوات ')
    textOf(clients[1]).delete(0, 4)
    textOf(clients[1]).insert(0, 'يشرح')
    textOf(clients[2]).insert(19, ' بدقة')
    fullSync(clients)

    const rows = expectConverged(clients)
    const text = (rows.blocks[0].content as { content: Array<{ content: Array<{ text: string }> }> }).content[0].content.map((t) => t.text).join('')
    // Both inserts land after the deleted "يصف " with the same origin, so Yjs orders them
    // by client id: "يشرحخطوات " or "خطوات يشرح" are both valid, as long as every client agrees.
    expect(text).toContain('خطوات')
    expect(text).toContain('يشرح')
    expect(text).toContain('بدقة')
    expect(text).not.toContain('يصف')
    expect(text.endsWith('الإجراء بدقة')).toBe(true)
  })

  it(`${NUM_RUNS} random sessions of 3-5 clients with partial syncs converge and materialize identically`, () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 3, max: 5 }),
        fc.uniqueArray(fc.integer({ min: 1, max: 1_000_000 }), { minLength: 5, maxLength: 5 }),
        structureArb(8),
        fc.array(opArb, { minLength: 20, maxLength: 80 }),
        fc.array(fc.tuple(fc.nat(), fc.nat()), { minLength: 0, maxLength: 20 }),
        (clientCount, clientIds, structure, ops, syncs) => {
          // Client ids decide tie-breaks in Yjs, so they are part of the seeded input.
          const clients = newCluster(clientCount, buildDoc(structure), clientIds)
          const syncQueue = [...syncs]
          ops.forEach((op: SimOp, i) => {
            applyOp(clients[op.client % clientCount], op)
            // Every few ops, deliver a random subset of pending updates in random order.
            if (i % 5 === 4 && syncQueue.length) {
              const [from, to] = syncQueue.shift()!
              partialSync(clients[from % clientCount], clients[to % clientCount])
            }
          })
          fullSync(clients)
          expectConverged(clients)
        },
      ),
      { seed: SEED, numRuns: NUM_RUNS },
    )
  })
})
