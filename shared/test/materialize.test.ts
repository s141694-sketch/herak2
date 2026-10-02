import fc from 'fast-check'
import { describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { editorSchema } from '../src/editor'
import { hydrate, materialize, setBlockContent } from '../src/materialize'
import { addBlock, addLink, addNode, setBlockDeleted, setNodeDeleted } from '../src/operations'
import { blockFragment, nodesOf } from '../src/schema'
import { ARABIC_FIXTURE_JSON } from './arabic-fixture'
import { BLOCK_TYPE_ARB, richDocArb } from './arbitraries'

const SEED = Number(process.env.SHARED_SEED ?? 20261003)
const RUNS = Number(process.env.SHARED_RUNS ?? 1000)

function fixtureDoc() {
  const doc = new Y.Doc()
  const root = addNode(doc, { parent: null, title: 'برنامج السلامة' }, 5)
  const module = addNode(doc, { parent: root, title: 'الوحدة الأولى: مقدّمة' }, 5)
  const lesson = addNode(doc, { parent: module, title: 'Lesson ١: Mixed عنوان' }, 5)
  const gone = addNode(doc, { parent: module, title: 'محذوفة' }, 5)
  setNodeDeleted(doc, gone, true)
  const objective = addBlock(doc, { node_key: lesson, type: 'objective' })
  const assessment = addBlock(doc, { node_key: lesson, type: 'assessment' })
  const empty = addBlock(doc, { node_key: root, type: 'reference' })
  const deleted = addBlock(doc, { node_key: module, type: 'content' })
  setBlockDeleted(doc, deleted, true)
  setBlockContent(doc, objective, ARABIC_FIXTURE_JSON)
  setBlockContent(doc, assessment, { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'سؤال ١: ما الـ PPE؟' }] }] })
  setBlockContent(doc, deleted, { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'محذوف' }] }] })
  addLink(doc, { kind: 'assessment_objective', source_key: assessment, target_key: objective })
  addLink(doc, { kind: 'objective_competency', source_key: objective, competency_key: '6f2c1d3e-0000-4000-8000-000000000001' })
  return { doc, keys: { root, module, lesson, objective, assessment, empty, deleted } }
}

describe('materialize and hydrate', () => {
  it('emits nodes in tree order with computed levels, blocks with canonical content, and links', () => {
    const { doc, keys } = fixtureDoc()
    const rows = materialize(doc)
    expect(rows.issues).toEqual([])
    expect(rows.nodes.map((n) => [n.title, n.level])).toEqual([
      ['برنامج السلامة', 0],
      ['الوحدة الأولى: مقدّمة', 1],
      ['Lesson ١: Mixed عنوان', 2],
      ['محذوفة', 2],
    ])
    const objective = rows.blocks.find((b) => b.block_key === keys.objective)!
    expect(objective.content).toEqual(editorSchema.nodeFromJSON(ARABIC_FIXTURE_JSON).toJSON())
    for (const needle of ['يَصِفُ', '‏', '‫', '‌', 'ـ', '١٠٠٪']) expect(JSON.stringify(objective.content)).toContain(needle)
    expect(rows.links.map((l) => l.kind).sort()).toEqual(['assessment_objective', 'objective_competency'])
  })

  it('round-trips doc -> rows -> doc -> rows with no loss', () => {
    const { doc } = fixtureDoc()
    const rows = materialize(doc)
    const rebuilt = hydrate(rows)
    expect(materialize(rebuilt)).toEqual(rows)
    for (const block of rows.blocks) expect(blockFragment(rebuilt, block.block_key).toString()).toBe(blockFragment(doc, block.block_key).toString())
  })

  it('repairs orphans and cycles deterministically and drops dangling blocks and links', () => {
    const { doc, keys } = fixtureDoc()
    nodesOf(doc).get(keys.lesson)!.set('parent', 'ghost')
    nodesOf(doc).get(keys.root)!.set('parent', keys.module)
    const lost = addBlock(doc, { node_key: keys.root, type: 'content' })
    nodesOf(doc).delete(keys.root)
    const rows = materialize(doc)
    expect(rows.issues.map((i) => i.kind).sort()).toEqual(['dangling_block', 'orphan'].sort())
    expect(rows.blocks.some((b) => b.block_key === lost)).toBe(false)
    const replica = new Y.Doc()
    Y.applyUpdate(replica, Y.encodeStateAsUpdate(doc))
    expect(materialize(replica)).toEqual(rows)
  })

  it(`round-trips ${RUNS} random documents with Arabic content`, () => {
    const structure = fc.record({
      parents: fc.array(fc.nat({ max: 1000 }), { minLength: 1, maxLength: 25 }),
      blocks: fc.array(fc.tuple(fc.nat({ max: 1000 }), BLOCK_TYPE_ARB, richDocArb, fc.boolean()), { maxLength: 30 }),
      titles: fc.array(fc.string({ maxLength: 20, unit: 'grapheme' }), { minLength: 25, maxLength: 25 }),
    })
    fc.assert(
      fc.property(structure, ({ parents, blocks, titles }) => {
        const doc = new Y.Doc()
        const keys: string[] = []
        parents.forEach((pick, i) => {
          const candidates = keys.filter((k) => {
            let depth = 0
            let p = nodesOf(doc).get(k)?.get('parent') as string | null
            while (p) (depth += 1), (p = nodesOf(doc).get(p)?.get('parent') as string | null)
            return depth < 4
          })
          const parent = i === 0 || pick % 5 === 0 || !candidates.length ? null : candidates[pick % candidates.length]
          keys.push(addNode(doc, { parent, title: titles[i] }, 5))
        })
        for (const [pick, type, content, deleted] of blocks) {
          const key = addBlock(doc, { node_key: keys[pick % keys.length], type })
          setBlockContent(doc, key, content)
          if (deleted) setBlockDeleted(doc, key, true)
          expect(materialize(doc).blocks.find((b) => b.block_key === key)!.content).toEqual(editorSchema.nodeFromJSON(content).toJSON())
        }
        const rows = materialize(doc)
        expect(rows.issues).toEqual([])
        expect(materialize(hydrate(rows))).toEqual(rows)
      }),
      { seed: SEED, numRuns: RUNS },
    )
  })
})
