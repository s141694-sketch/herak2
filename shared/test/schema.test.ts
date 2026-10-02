import { describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { addBlock, addLink, addNode, depthOf, DocumentRuleError, moveNode, renameNode, setBlockDeleted, setNodeDeleted } from '../src/operations'
import { blockFragment, blocksOf, linksOf, nodesOf, readBlock, readNode } from '../src/schema'

const LEVELS = 4

function tree(doc: Y.Doc) {
  const root = addNode(doc, { parent: null, title: 'البرنامج' }, LEVELS)
  const module = addNode(doc, { parent: root, title: 'الوحدة' }, LEVELS)
  const lesson = addNode(doc, { parent: module, title: 'الدرس' }, LEVELS)
  const activity = addNode(doc, { parent: lesson, title: 'النشاط' }, LEVELS)
  return { root, module, lesson, activity }
}

const code = (fn: () => unknown) => {
  try {
    fn()
  } catch (error) {
    return (error as DocumentRuleError).code
  }
  return null
}

describe('live document schema and operations', () => {
  it('builds a four-level tree within the template and refuses a fifth level', () => {
    const doc = new Y.Doc()
    const { root, lesson, activity } = tree(doc)
    expect(depthOf(doc, activity)).toBe(3)
    expect(readNode(nodesOf(doc).get(root)!)).toEqual({ parent: null, order: 1, title: 'البرنامج', deleted: false })
    expect(code(() => addNode(doc, { parent: activity, title: 'x' }, LEVELS))).toBe('node_level_exceeds_template')
    const second = addNode(doc, { parent: lesson, title: 'نشاط ثانٍ' }, LEVELS)
    expect(readNode(nodesOf(doc).get(second)!).order).toBe(2)
  })

  it('moves nodes, refusing cycles and branches deeper than the template', () => {
    const doc = new Y.Doc()
    const { root, module, lesson } = tree(doc)
    const module2 = addNode(doc, { parent: root, title: 'الوحدة الثانية' }, LEVELS)
    moveNode(doc, lesson, { parent: module2 }, LEVELS)
    expect(readNode(nodesOf(doc).get(lesson)!).parent).toBe(module2)
    expect(code(() => moveNode(doc, module2, { parent: lesson }, LEVELS))).toBe('node_move_cycle')
    expect(code(() => moveNode(doc, module2, { parent: module }, LEVELS))).toBe('node_level_exceeds_template')
  })

  it('stores blocks of every type with a nested fragment, and links between them', () => {
    const doc = new Y.Doc()
    const { lesson } = tree(doc)
    const objective = addBlock(doc, { node_key: lesson, type: 'objective' })
    const assessment = addBlock(doc, { node_key: lesson, type: 'assessment' })
    expect(readBlock(blocksOf(doc).get(objective)!)).toEqual({ node_key: lesson, type: 'objective', order: 1, deleted: false })
    expect(blockFragment(doc, assessment)).toBeInstanceOf(Y.XmlFragment)
    addLink(doc, { kind: 'assessment_objective', source_key: assessment, target_key: objective })
    expect(code(() => addLink(doc, { kind: 'assessment_objective', source_key: assessment, target_key: objective }))).toBe('link_exists')
    expect(linksOf(doc).size).toBe(1)
    expect(code(() => addBlock(doc, { node_key: 'missing', type: 'content' }))).toBe('block_node_invalid')
  })

  it('soft deletes and renames', () => {
    const doc = new Y.Doc()
    const { module } = tree(doc)
    const block = addBlock(doc, { node_key: module, type: 'content' })
    setNodeDeleted(doc, module, true)
    setBlockDeleted(doc, block, true)
    renameNode(doc, module, '  الوحدة المعدّلة ')
    expect(readNode(nodesOf(doc).get(module)!)).toMatchObject({ deleted: true, title: 'الوحدة المعدّلة' })
    expect(readBlock(blocksOf(doc).get(block)!).deleted).toBe(true)
  })
})
