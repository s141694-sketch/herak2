import { describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { blockFragment, createBlock, createNode, nodesMap, softDeleteBlock, softDeleteNode } from '../src/schema'
import { editorSchema, hydrate, materialize, setBlockContent, type Rows } from '../src/materialize'
import { ARABIC_FIXTURE_JSON } from './fixtures/arabic-doc'

function buildFixtureDoc(): Y.Doc {
  const doc = new Y.Doc()
  createNode(doc, 'course', { parent: null, order: 0 })
  createNode(doc, 'module-1', { parent: 'course', order: 0 })
  createNode(doc, 'module-2', { parent: 'course', order: 1 })
  createNode(doc, 'unit-1-1', { parent: 'module-1', order: 0 })
  createNode(doc, 'unit-1-2', { parent: 'module-1', order: 1 })
  createNode(doc, 'unit-2-1', { parent: 'module-2', order: 0 })
  softDeleteNode(doc, 'unit-1-2')

  createBlock(doc, 'b-objective', { node_key: 'unit-1-1', type: 'objective' })
  createBlock(doc, 'b-content', { node_key: 'unit-1-1', type: 'content' })
  createBlock(doc, 'b-activity', { node_key: 'module-1', type: 'activity' })
  createBlock(doc, 'b-assessment', { node_key: 'unit-2-1', type: 'assessment' })
  createBlock(doc, 'b-reference', { node_key: 'course', type: 'reference' })
  createBlock(doc, 'b-empty', { node_key: 'course', type: 'content' })
  createBlock(doc, 'b-deleted', { node_key: 'unit-1-1', type: 'content' })
  softDeleteBlock(doc, 'b-deleted')

  setBlockContent(doc, 'b-objective', ARABIC_FIXTURE_JSON)
  setBlockContent(doc, 'b-content', { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'English only content.' }] }] })
  setBlockContent(doc, 'b-activity', { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'نشاط: ناقش مع زميلك' }] }] })
  setBlockContent(doc, 'b-assessment', { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'سؤال ١: ما هو الـ PPE؟' }] }] })
  setBlockContent(doc, 'b-reference', { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'المرجع: OSHA 2024' }] }] })
  setBlockContent(doc, 'b-deleted', { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'محذوف' }] }] })
  return doc
}

describe('materialize / hydrate round trip (task 0.3)', () => {
  it('materializes nodes with computed depth and deterministic order', () => {
    const rows = materialize(buildFixtureDoc())
    expect(rows.issues).toEqual([])
    expect(rows.nodes.map((n) => n.node_key)).toEqual(['course', 'module-1', 'unit-1-1', 'unit-1-2', 'module-2', 'unit-2-1'])
    expect(rows.nodes.find((n) => n.node_key === 'unit-2-1')).toEqual({ node_key: 'unit-2-1', parent_key: 'module-2', level: 2, order: 0, deleted: false })
    expect(rows.nodes.find((n) => n.node_key === 'unit-1-2')!.deleted).toBe(true)
  })

  it('materializes block content as canonical TipTap JSON, byte-for-byte equal to the input', () => {
    const rows = materialize(buildFixtureDoc())
    const objective = rows.blocks.find((b) => b.block_key === 'b-objective')!
    const canonical = editorSchema.nodeFromJSON(ARABIC_FIXTURE_JSON).toJSON()
    expect(objective.content).toEqual(canonical)
    // Code points survive exactly: diacritics, bidi controls, tatweel, ZWNJ.
    const text = JSON.stringify(objective.content)
    for (const needle of ['يَصِفُ', '‏', '‎', '‫', '‬', '‌', 'ـ', '١٠٠٪']) {
      expect(text).toContain(needle)
    }
    expect(rows.blocks.find((b) => b.block_key === 'b-empty')!.content).toEqual({ type: 'doc' })
    expect(rows.blocks.find((b) => b.block_key === 'b-deleted')!.deleted).toBe(true)
  })

  it('round-trips doc -> rows -> doc -> rows with no loss', () => {
    const original = buildFixtureDoc()
    const rows1: Rows = materialize(original)
    const rebuilt = hydrate(rows1)
    const rows2 = materialize(rebuilt)
    expect(rows2).toEqual(rows1)
    // And the Yjs XML of every block is identical, not only the JSON.
    for (const block of rows1.blocks) {
      expect(blockFragment(rebuilt, block.block_key).toString()).toBe(blockFragment(original, block.block_key).toString())
    }
  })

  it('round-trips a document that was replicated through Yjs updates', () => {
    const original = buildFixtureDoc()
    const replica = new Y.Doc()
    Y.applyUpdate(replica, Y.encodeStateAsUpdate(original))
    expect(materialize(replica)).toEqual(materialize(original))
    expect(materialize(hydrate(materialize(replica)))).toEqual(materialize(original))
  })

  it('repairs orphans and cycles deterministically and reports them', () => {
    const doc = buildFixtureDoc()
    // Orphan: parent key that does not exist.
    nodesMap(doc).get('unit-2-1')!.set('parent', 'ghost')
    // Cycle: module-1 -> unit-1-1 -> module-1 (unit-1-1 is already under module-1).
    nodesMap(doc).get('module-1')!.set('parent', 'unit-1-1')
    const rows = materialize(doc)
    expect(rows.issues.map((i) => i.kind).sort()).toEqual(['cycle', 'orphan'])
    expect(rows.nodes.find((n) => n.node_key === 'unit-2-1')!.parent_key).toBeNull()
    const cycleMembers = rows.issues.find((i) => i.kind === 'cycle')!.node_keys.sort()
    expect(cycleMembers).toEqual(['module-1', 'unit-1-1'])
    // Smallest key in the cycle is reattached to the root; everyone reaches the same result.
    expect(rows.nodes.find((n) => n.node_key === 'module-1')!.parent_key).toBeNull()
    expect(rows.nodes.find((n) => n.node_key === 'unit-1-1')!.parent_key).toBe('module-1')
    const replica = new Y.Doc()
    Y.applyUpdate(replica, Y.encodeStateAsUpdate(doc))
    expect(materialize(replica)).toEqual(rows)
  })
})
