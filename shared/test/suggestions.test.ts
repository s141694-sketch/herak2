import { describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { hydrate, materialize, setBlockContent } from '../src/materialize'
import { addBlock, addNode } from '../src/operations'
import { applyOutline, applyRewrite, blockPlainText } from '../src/suggestions'

const paragraph = (text: string) => ({ type: 'paragraph', content: [{ type: 'text', text }] })

function draft() {
  const doc = new Y.Doc()
  const root = addNode(doc, { parent: null, title: 'الوحدة' }, 2)
  const block = addBlock(doc, { node_key: root, type: 'objective' })
  setBlockContent(doc, block, {
    type: 'doc',
    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'أن يفهم ' }, { type: 'text', text: 'المتدرب', marks: [{ type: 'bold' }] }, { type: 'text', text: ' الإسعافات' }] }],
  })
  return { doc, root, block }
}

describe('a rewrite', () => {
  it('reads a block as the server does: plain characters, paragraphs on their own lines', () => {
    const { doc, block } = draft()
    expect(blockPlainText(doc, block)).toBe('أن يفهم المتدرب الإسعافات')
    setBlockContent(doc, block, { type: 'doc', content: [paragraph('سطر أول'), paragraph('سطر ثان')] })
    expect(blockPlainText(doc, block)).toBe('سطر أول\nسطر ثان')
  })

  it('replaces the text it was made for', () => {
    const { doc, block } = draft()
    expect(applyRewrite(doc, block, 'أن يفهم  المتدرب الإسعافات ', 'أن يقدم المتدرب الإسعافات الأولية')).toBe('applied')
    expect(materialize(doc).blocks[0].content).toEqual({ type: 'doc', content: [paragraph('أن يقدم المتدرب الإسعافات الأولية')] })
  })

  it('leaves a text that changed since the suggestion was asked for', () => {
    const { doc, block } = draft()
    const before = Y.encodeStateAsUpdate(doc)
    expect(applyRewrite(doc, block, 'نص آخر', 'أن يقدم المتدرب الإسعافات')).toBe('changed')
    expect(applyRewrite(doc, 'missing-block', 'أن يفهم المتدرب الإسعافات', 'x')).toBe('missing')
    expect(Y.encodeStateAsUpdate(doc)).toEqual(before)
  })
})

describe('an outline', () => {
  const outline = {
    nodes: [
      { ref: 'n1', parent: '', title: 'السلامة في الموقع' },
      { ref: 'n2', parent: 'n1', title: 'الإسعافات الأولية' },
    ],
    objectives: [{ node: 'n2', text: 'أن يقدم المتدرب الإسعافات الأولية لمصاب بنزيف', competency_key: 'c-1' }],
  }

  it('adds its nodes, objectives and their links to the competencies, after what is there', () => {
    const { doc } = draft()
    expect(applyOutline(doc, outline, 2)).toEqual({ nodes: 2, objectives: 1 })
    const rows = materialize(doc)
    const added = rows.nodes.filter((n) => n.title !== 'الوحدة')
    expect(added.map((n) => [n.title, n.level])).toEqual([
      ['السلامة في الموقع', 0],
      ['الإسعافات الأولية', 1],
    ])
    expect(added[0].order).toBeGreaterThan(rows.nodes.find((n) => n.title === 'الوحدة')!.order)
    const objective = rows.blocks.find((b) => JSON.stringify(b.content).includes('لمصاب بنزيف'))!
    expect(objective.type).toBe('objective')
    expect(objective.node_key).toBe(added[1].node_key)
    expect(rows.links).toEqual([expect.objectContaining({ kind: 'objective_competency', source_key: objective.block_key, competency_key: 'c-1' })])
  })

  it('is applied as one change, or not at all when a rule refuses part of it', () => {
    const { doc } = draft()
    const updates: Uint8Array[] = []
    doc.on('update', (update: Uint8Array) => updates.push(update))
    applyOutline(doc, outline, 2)
    expect(updates).toHaveLength(1)
    const before = Y.encodeStateAsUpdate(doc)
    const tooDeep = { ...outline, nodes: [...outline.nodes, { ref: 'n3', parent: 'n2', title: 'أعمق' }] }
    expect(() => applyOutline(doc, tooDeep, 2)).toThrow()
    expect(Y.encodeStateAsUpdate(doc)).toEqual(before)
    expect(materialize(hydrate(materialize(doc))).nodes).toHaveLength(3)
  })
})
