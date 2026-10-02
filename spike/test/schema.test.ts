import { describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import {
  BLOCK_TYPES,
  blockFragment,
  createBlock,
  createNode,
  getBlock,
  getNode,
  listBlocks,
  listNodes,
  moveNode,
  softDeleteBlock,
  softDeleteNode,
} from '../src/schema'

function buildThreeLevelTree(doc: Y.Doc) {
  createNode(doc, 'course', { parent: null, order: 0 })
  createNode(doc, 'module-1', { parent: 'course', order: 0 })
  createNode(doc, 'module-2', { parent: 'course', order: 1 })
  createNode(doc, 'unit-1-1', { parent: 'module-1', order: 0 })
  createNode(doc, 'unit-1-2', { parent: 'module-1', order: 1 })
  createNode(doc, 'unit-2-1', { parent: 'module-2', order: 0 })
}

describe('Yjs document schema (task 0.2)', () => {
  it('stores a three-level tree in the nodes map with parent, level, order and deleted', () => {
    const doc = new Y.Doc()
    buildThreeLevelTree(doc)

    expect(getNode(doc, 'course')).toEqual({ parent: null, level: 0, order: 0, deleted: false })
    expect(getNode(doc, 'module-1')).toEqual({ parent: 'course', level: 1, order: 0, deleted: false })
    expect(getNode(doc, 'unit-1-2')).toEqual({ parent: 'module-1', level: 2, order: 1, deleted: false })
    expect(listNodes(doc).map((n) => n.key).sort()).toEqual(
      ['course', 'module-1', 'module-2', 'unit-1-1', 'unit-1-2', 'unit-2-1'].sort(),
    )
  })

  it('stores a block of every type with a nested XmlFragment as content', () => {
    const doc = new Y.Doc()
    buildThreeLevelTree(doc)
    expect(BLOCK_TYPES).toEqual(['objective', 'content', 'activity', 'assessment', 'reference'])

    for (const type of BLOCK_TYPES) {
      createBlock(doc, `block-${type}`, { node_key: 'unit-1-1', type })
    }

    for (const type of BLOCK_TYPES) {
      const block = getBlock(doc, `block-${type}`)
      expect(block).toEqual({ node_key: 'unit-1-1', type, deleted: false })
      expect(blockFragment(doc, `block-${type}`)).toBeInstanceOf(Y.XmlFragment)
    }
    expect(listBlocks(doc)).toHaveLength(5)

    // The fragment is live: content written to it is readable back as XML.
    const fragment = blockFragment(doc, 'block-objective')
    const paragraph = new Y.XmlElement('paragraph')
    paragraph.insert(0, [new Y.XmlText('يصف المتدرب خطوات الإجراء')])
    fragment.insert(0, [paragraph])
    expect(fragment.toString()).toBe('<paragraph>يصف المتدرب خطوات الإجراء</paragraph>')
  })

  it('rejects an unknown block type and a block on a missing node', () => {
    const doc = new Y.Doc()
    buildThreeLevelTree(doc)
    expect(() => createBlock(doc, 'b', { node_key: 'unit-1-1', type: 'quiz' as never })).toThrow()
    expect(() => createBlock(doc, 'b', { node_key: 'no-such-node', type: 'content' })).toThrow()
  })

  it('soft deletes nodes and blocks without removing them', () => {
    const doc = new Y.Doc()
    buildThreeLevelTree(doc)
    createBlock(doc, 'b1', { node_key: 'unit-2-1', type: 'content' })

    softDeleteNode(doc, 'unit-2-1')
    softDeleteBlock(doc, 'b1')

    expect(getNode(doc, 'unit-2-1').deleted).toBe(true)
    expect(getBlock(doc, 'b1').deleted).toBe(true)
    expect(listNodes(doc)).toHaveLength(6)
    expect(listBlocks(doc)).toHaveLength(1)
  })

  it('moves a node under a new parent and updates level and order', () => {
    const doc = new Y.Doc()
    buildThreeLevelTree(doc)

    moveNode(doc, 'unit-1-2', { parent: 'module-2', order: 1 })

    expect(getNode(doc, 'unit-1-2')).toEqual({ parent: 'module-2', level: 2, order: 1, deleted: false })
    moveNode(doc, 'module-2', { parent: 'module-1', order: 2 })
    expect(getNode(doc, 'module-2').level).toBe(2)
    // Stored level of descendants follows the move.
    expect(getNode(doc, 'unit-2-1').level).toBe(3)
    expect(getNode(doc, 'unit-1-2').level).toBe(3)
  })

  it('replicates the whole structure, including nested fragments, to a second document', () => {
    const doc = new Y.Doc()
    buildThreeLevelTree(doc)
    createBlock(doc, 'b1', { node_key: 'unit-1-1', type: 'objective' })
    const paragraph = new Y.XmlElement('paragraph')
    paragraph.insert(0, [new Y.XmlText('Mixed نص text')])
    blockFragment(doc, 'b1').insert(0, [paragraph])

    const replica = new Y.Doc()
    Y.applyUpdate(replica, Y.encodeStateAsUpdate(doc))

    expect(listNodes(replica)).toEqual(listNodes(doc))
    expect(listBlocks(replica)).toEqual(listBlocks(doc))
    expect(blockFragment(replica, 'b1').toString()).toBe('<paragraph>Mixed نص text</paragraph>')
  })
})
