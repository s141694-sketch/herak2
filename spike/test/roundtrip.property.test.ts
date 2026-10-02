import fc from 'fast-check'
import { describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { editorSchema, hydrate, materialize, setBlockContent } from '../src/materialize'
import { blockFragment, createBlock, createNode, softDeleteBlock, softDeleteNode } from '../src/schema'
import { type GeneratedStructure, structureArb } from './arbitraries'

// Fixed seed so any failure is reproducible; change NUM_RUNS via env for longer soaks.
export const SEED = Number(process.env.SPIKE_SEED ?? 20261003)
const NUM_RUNS = Number(process.env.SPIKE_RUNS ?? 1000)

export function buildDoc(structure: GeneratedStructure): Y.Doc {
  const doc = new Y.Doc()
  doc.transact(() => {
    for (const node of structure.nodes) {
      createNode(doc, node.key, { parent: node.parent, order: node.order })
      if (node.deleted) softDeleteNode(doc, node.key)
    }
    for (const block of structure.blocks) {
      createBlock(doc, block.key, { node_key: block.node_key, type: block.type })
      setBlockContent(doc, block.key, block.content)
      if (block.deleted) softDeleteBlock(doc, block.key)
    }
  })
  return doc
}

describe(`property-based round trip, ${NUM_RUNS} random documents (task 0.4)`, () => {
  it('doc -> rows -> doc -> rows loses nothing, and rows equal the canonical input', () => {
    fc.assert(
      fc.property(structureArb(30), (structure) => {
        // Only documents the editor could actually produce are meaningful.
        for (const block of structure.blocks) editorSchema.nodeFromJSON(block.content).check()

        const doc = buildDoc(structure)
        const rows = materialize(doc)
        expect(rows.issues).toEqual([])
        expect(rows.nodes).toHaveLength(structure.nodes.length)
        expect(rows.blocks).toHaveLength(structure.blocks.length)

        for (const block of structure.blocks) {
          const row = rows.blocks.find((b) => b.block_key === block.key)!
          expect(row.content).toEqual(editorSchema.nodeFromJSON(block.content).toJSON())
          expect(row.deleted).toBe(block.deleted)
          expect(row.node_key).toBe(block.node_key)
        }

        const rebuilt = hydrate(rows)
        expect(materialize(rebuilt)).toEqual(rows)
        for (const block of rows.blocks) {
          expect(blockFragment(rebuilt, block.block_key).toString()).toBe(blockFragment(doc, block.block_key).toString())
        }

        // A replica built from the binary update materializes identically.
        const replica = new Y.Doc()
        Y.applyUpdate(replica, Y.encodeStateAsUpdate(doc))
        expect(materialize(replica)).toEqual(rows)
      }),
      { seed: SEED, numRuns: NUM_RUNS },
    )
  })
})
