import fc from 'fast-check'
import { describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { createAnchor, deserializeAnchor, reanchorByText, resolveAnchor, serializeAnchor } from '../src/anchors'
import { hydrate, materialize, setBlockContent } from '../src/materialize'
import { addBlock, addNode } from '../src/operations'
import { blockFragment } from '../src/schema'

const SENTENCE = 'يصف المتدرب خطوات الإجراء بدقة'
const QUOTE = 'خطوات الإجراء'
const FROM = SENTENCE.indexOf(QUOTE)
const TO = FROM + QUOTE.length

function seed() {
  const doc = new Y.Doc()
  const node = addNode(doc, { parent: null, title: 'n' }, 5)
  addBlock(doc, { node_key: node, type: 'objective', key: 'b1' })
  setBlockContent(doc, 'b1', { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'تمهيد' }] }, { type: 'paragraph', content: [{ type: 'text', text: SENTENCE }] }] })
  return doc
}

const textOf = (doc: Y.Doc, p = 1) => (blockFragment(doc, 'b1').get(p) as Y.XmlElement).get(0) as Y.XmlText

function replicas(doc: Y.Doc, n: number) {
  return Array.from({ length: n }, (_, i) => {
    const r = new Y.Doc()
    r.clientID = 100 + i
    Y.applyUpdate(r, Y.encodeStateAsUpdate(doc))
    return r
  })
}

function sync(docs: Y.Doc[]) {
  for (const a of docs) for (const b of docs) if (a !== b) Y.applyUpdate(b, Y.encodeStateAsUpdate(a, Y.encodeStateVector(b)))
}

describe('comment anchors', () => {
  it('survive concurrent edits before, after and at the boundaries', () => {
    const doc = seed()
    const anchor = createAnchor('b1', textOf(doc), FROM, TO)
    const [a, b, c] = replicas(doc, 3)
    textOf(a).insert(0, 'أولًا، ')
    textOf(b).insert(FROM, 'كل ')
    textOf(c).insert(TO, ' المطلوبة')
    textOf(c).insert(textOf(c).length, '!')
    sync([a, b, c])
    for (const r of [a, b, c]) expect(resolveAnchor(r, anchor)).toMatchObject({ status: 'intact', current: QUOTE })
  })

  it('report changed and orphaned states', () => {
    const doc = seed()
    const anchor = createAnchor('b1', textOf(doc), FROM, TO)
    const [a, b] = replicas(doc, 2)
    textOf(a).delete(FROM, 'خطوات'.length)
    textOf(a).insert(FROM, 'مراحل')
    sync([a, b])
    expect(resolveAnchor(b, anchor)).toMatchObject({ status: 'changed', current: 'مراحل الإجراء' })
    blockFragment(b, 'b1').delete(1, 1)
    sync([a, b])
    expect(resolveAnchor(a, anchor).status).toBe('orphaned')
  })

  it('serialize, survive a Yjs state copy, and fall back to text search after hydrate', () => {
    const doc = seed()
    const stored = serializeAnchor(createAnchor('b1', textOf(doc), FROM, TO))
    const copy = new Y.Doc()
    Y.applyUpdate(copy, Y.encodeStateAsUpdate(doc))
    textOf(copy).insert(0, 'إضافة ')
    expect(resolveAnchor(copy, deserializeAnchor(stored))).toMatchObject({ status: 'intact', current: QUOTE })

    const rebuilt = hydrate(materialize(doc))
    expect(resolveAnchor(rebuilt, deserializeAnchor(stored)).status).toBe('orphaned')
    const again = reanchorByText(rebuilt, deserializeAnchor(stored))
    expect(again.status).toBe('reanchored')
    expect(resolveAnchor(rebuilt, again.anchor!)).toMatchObject({ status: 'intact', current: QUOTE })
  })

  it('stay intact under 200 random concurrent edits outside the range', () => {
    fc.assert(
      fc.property(
        fc.array(fc.record({ who: fc.nat({ max: 2 }), before: fc.boolean(), insert: fc.boolean(), at: fc.nat({ max: 50 }), text: fc.constantFrom('أ', 'بسم ', 'x', '١٢٣', '، ') }), { minLength: 1, maxLength: 25 }),
        (ops) => {
          const doc = seed()
          const anchor = createAnchor('b1', textOf(doc), FROM, TO)
          const docs = replicas(doc, 3)
          for (const o of ops) {
            const r = resolveAnchor(docs[o.who], anchor)
            const text = textOf(docs[o.who])
            if (o.before) {
              const at = o.at % (r.from! + 1)
              if (o.insert) text.insert(at, o.text)
              else if (at < r.from!) text.delete(at, 1)
            } else {
              const at = r.to! + (o.at % (text.length - r.to! + 1))
              if (o.insert) text.insert(at, o.text)
              else if (at < text.length) text.delete(at, 1)
            }
          }
          sync(docs)
          for (const r of docs) expect(resolveAnchor(r, anchor)).toMatchObject({ status: 'intact', current: QUOTE })
        },
      ),
      { seed: 20261003, numRuns: 200 },
    )
  })
})
