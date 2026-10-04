import { describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { hydrate, materialize, setBlockContent } from '../src/materialize'
import { addBlock, addNode } from '../src/operations'
import { applyImport, applyOutline, applyRewrite, blockPlainText, checkImport, checkOutline, rewriteState } from '../src/suggestions'

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

  it('reads a hard line break as the server does, as a new line', () => {
    const { doc, block } = draft()
    setBlockContent(doc, block, {
      type: 'doc',
      content: [{ type: 'paragraph', content: [{ type: 'text', text: 'أن يعدد' }, { type: 'hardBreak' }, { type: 'text', text: 'المتدرب' }] }],
    })
    expect(blockPlainText(doc, block)).toBe('أن يعدد\nالمتدرب')
    expect(applyRewrite(doc, block, 'أن يعدد\nالمتدرب', 'أن يعدد المتدرب المخاطر')).toBe('applied')
  })

  it('tells, without writing, whether the rewrite still fits the text', () => {
    const { doc, block } = draft()
    const before = Y.encodeStateAsUpdate(doc)
    expect(rewriteState(doc, block, 'أن يفهم المتدرب الإسعافات')).toBe('applied')
    expect(rewriteState(doc, block, 'نص آخر')).toBe('changed')
    expect(rewriteState(doc, 'missing-block', 'x')).toBe('missing')
    expect(Y.encodeStateAsUpdate(doc)).toEqual(before)
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

  it('is checked on a copy without changing the document', () => {
    const { doc } = draft()
    const before = Y.encodeStateAsUpdate(doc)
    expect(() => checkOutline(doc, outline, 2)).not.toThrow()
    const tooDeep = { ...outline, nodes: [...outline.nodes, { ref: 'n3', parent: 'n2', title: 'أعمق' }] }
    expect(() => checkOutline(doc, tooDeep, 2)).toThrow()
    expect(Y.encodeStateAsUpdate(doc)).toEqual(before)
  })
})

describe('an import', () => {
  const layout = {
    nodes: [
      { ref: 'u1', parent: '', title: 'الوحدة الأولى: المخاطر' },
      { ref: 'u1l1', parent: 'u1', title: 'الدرس الأول: تحديد المخاطر' },
    ],
    blocks: [
      { node: 'u1l1', type: 'objective' as const, text: 'أن يعدد المتدرب أنواع المخاطر.' },
      { node: 'u1l1', type: 'activity' as const, text: 'نشاط: جولة ميدانية.\nتطبيق: تعبئة نموذج.' },
      { node: 'u1', type: 'content' as const, text: 'مقدمة الوحدة.' },
    ],
  }

  it('adds its nodes and blocks, each block of its type and with its lines as paragraphs', () => {
    const doc = new Y.Doc()
    expect(applyImport(doc, layout, 2)).toEqual({ nodes: 2, blocks: 3 })
    const rows = materialize(doc)
    expect(rows.nodes.map((n) => [n.title, n.level])).toEqual([
      ['الوحدة الأولى: المخاطر', 0],
      ['الدرس الأول: تحديد المخاطر', 1],
    ])
    const lesson = rows.nodes[1].node_key
    expect(rows.blocks.filter((b) => b.node_key === lesson).map((b) => b.type)).toEqual(['objective', 'activity'])
    const activity = rows.blocks.find((b) => b.type === 'activity')!
    expect(activity.content).toEqual({ type: 'doc', content: [paragraph('نشاط: جولة ميدانية.'), paragraph('تطبيق: تعبئة نموذج.')] })
    expect(rows.links).toEqual([])
  })

  it('changes nothing when the template refuses part of it', () => {
    const doc = new Y.Doc()
    expect(() => applyImport(doc, layout, 1)).toThrow()
    expect(materialize(doc).nodes).toEqual([])
  })

  it('is checked on a copy without changing the document', () => {
    const doc = new Y.Doc()
    expect(() => checkImport(doc, layout, 2)).not.toThrow()
    expect(() => checkImport(doc, layout, 1)).toThrow()
    expect(materialize(doc).nodes).toEqual([])
  })
})
