import fc from 'fast-check'
import { describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { type Anchor, createAnchor, deserializeAnchor, reanchorByText, resolveAnchor, serializeAnchor } from '../src/anchors'
import { hydrate, materialize, setBlockContent } from '../src/materialize'
import { blockFragment, createBlock, createNode } from '../src/schema'
import { type Client, fullSync, newCluster } from './simulation'

const SENTENCE = 'يصف المتدرب خطوات الإجراء بدقة' // anchor on "خطوات الإجراء"
const QUOTE = 'خطوات الإجراء'
const FROM = SENTENCE.indexOf(QUOTE)
const TO = FROM + QUOTE.length
const SEED = Number(process.env.SPIKE_SEED ?? 20261003)

function seedDoc(): Y.Doc {
  const doc = new Y.Doc()
  createNode(doc, 'root', { parent: null, order: 0 })
  createBlock(doc, 'b1', { node_key: 'root', type: 'objective' })
  setBlockContent(doc, 'b1', {
    type: 'doc',
    content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'فقرة تمهيدية' }] },
      { type: 'paragraph', content: [{ type: 'text', text: SENTENCE }] },
    ],
  })
  return doc
}

function textOf(c: Client | Y.Doc, paragraph = 1): Y.XmlText {
  const doc = c instanceof Y.Doc ? c : c.doc
  return (blockFragment(doc, 'b1').get(paragraph) as Y.XmlElement).get(0) as Y.XmlText
}

function anchored(): { clients: Client[]; anchor: Anchor } {
  const seed = seedDoc()
  const anchor = createAnchor(seed, 'b1', textOf(seed), FROM, TO)
  expect(anchor.quoted).toBe(QUOTE)
  return { clients: newCluster(3, seed), anchor }
}

describe('comment anchors with Y.RelativePosition (task 0.6)', () => {
  it('survives concurrent inserts and deletes before and after the range', () => {
    const { clients, anchor } = anchored()
    textOf(clients[0]).insert(0, 'أولًا، ')
    textOf(clients[1]).insert(SENTENCE.length, ' وبسرعة.')
    textOf(clients[2]).delete(0, 4) // "يصف "
    textOf(clients[2]).insert(SENTENCE.length - 4, '!')
    fullSync(clients)
    for (const c of clients) {
      const r = resolveAnchor(c.doc, anchor)
      expect(r.status).toBe('intact')
      expect(r.current).toBe(QUOTE)
    }
  })

  it('does not swallow text inserted exactly at the start or end boundary', () => {
    const { clients, anchor } = anchored()
    textOf(clients[0]).insert(FROM, 'كل ')
    textOf(clients[1]).insert(TO, ' المطلوبة')
    fullSync(clients)
    for (const c of clients) expect(resolveAnchor(c.doc, anchor)).toMatchObject({ status: 'intact', current: QUOTE })
  })

  it('detects when the anchored text itself was deleted', () => {
    const { clients, anchor } = anchored()
    textOf(clients[0]).delete(FROM, QUOTE.length)
    textOf(clients[1]).insert(0, 'ثم ')
    fullSync(clients)
    for (const c of clients) expect(resolveAnchor(c.doc, anchor).status).toBe('orphaned')
  })

  it('detects when text inside the range changed, and reports the current text', () => {
    const { clients, anchor } = anchored()
    textOf(clients[0]).delete(FROM, 'خطوات'.length)
    textOf(clients[0]).insert(FROM, 'مراحل')
    fullSync(clients)
    for (const c of clients) expect(resolveAnchor(c.doc, anchor)).toMatchObject({ status: 'changed', current: 'مراحل الإجراء' })
  })

  it('detects when the whole paragraph holding the anchor was removed', () => {
    const { clients, anchor } = anchored()
    blockFragment(clients[1].doc, 'b1').delete(1, 1)
    fullSync(clients)
    for (const c of clients) expect(resolveAnchor(c.doc, anchor).status).toBe('orphaned')
  })

  it('serializes to a string and still resolves in a document reloaded from its Yjs update', () => {
    const seed = seedDoc()
    const anchor = createAnchor(seed, 'b1', textOf(seed), FROM, TO)
    const stored = serializeAnchor(anchor)
    expect(typeof stored).toBe('string')

    // A new draft created by copying the Yjs state keeps item identities, so anchors survive.
    const reloaded = new Y.Doc()
    Y.applyUpdate(reloaded, Y.encodeStateAsUpdate(seed))
    textOf(reloaded).insert(0, 'إضافة ')
    expect(resolveAnchor(reloaded, deserializeAnchor(stored))).toMatchObject({ status: 'intact', current: QUOTE })
  })

  it('cannot resolve in a document hydrated from rows, and falls back to re-anchoring by quoted text', () => {
    const seed = seedDoc()
    const anchor = createAnchor(seed, 'b1', textOf(seed), FROM, TO)
    const rebuilt = hydrate(materialize(seed))
    expect(resolveAnchor(rebuilt, anchor).status).toBe('orphaned')

    const again = reanchorByText(rebuilt, anchor)
    expect(again.status).toBe('reanchored')
    expect(resolveAnchor(rebuilt, again.anchor!)).toMatchObject({ status: 'intact', current: QUOTE })

    // Ambiguity is reported rather than guessed.
    textOf(rebuilt, 0).insert(0, QUOTE + ' ')
    expect(reanchorByText(rebuilt, anchor).status).toBe('ambiguous')
    textOf(rebuilt, 1).delete(FROM, QUOTE.length)
    textOf(rebuilt, 0).delete(0, QUOTE.length + 1)
    expect(reanchorByText(rebuilt, anchor).status).toBe('not_found')
  })

  it('stays intact under 200 random concurrent edits outside the range', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            client: fc.nat({ max: 2 }),
            side: fc.constantFrom('before', 'after'),
            kind: fc.constantFrom('insert', 'delete'),
            at: fc.nat({ max: 50 }),
            text: fc.constantFrom('أ', 'بسم ', 'x', '١٢٣', '، ', 'كلمة طويلة نسبيًا '),
            length: fc.integer({ min: 1, max: 3 }),
          }),
          { minLength: 1, maxLength: 25 },
        ),
        (ops) => {
          const { clients, anchor } = anchored()
          for (const op of ops) {
            const c = clients[op.client]
            const r = resolveAnchor(c.doc, anchor)
            if (r.status !== 'intact') throw new Error(`anchor lost before sync: ${r.status}`)
            const text = textOf(c)
            const len = text.length
            if (op.side === 'before') {
              const at = op.at % (r.from! + 1)
              if (op.kind === 'insert') text.insert(at, op.text)
              else if (at < r.from!) text.delete(at, Math.min(op.length, r.from! - at))
            } else {
              const at = r.to! + (op.at % (len - r.to! + 1))
              if (op.kind === 'insert') text.insert(at, op.text)
              else if (at < len) text.delete(at, Math.min(op.length, len - at))
            }
          }
          fullSync(clients)
          for (const c of clients) {
            const r = resolveAnchor(c.doc, anchor)
            expect(r).toMatchObject({ status: 'intact', current: QUOTE })
          }
        },
      ),
      { seed: SEED, numRuns: 200 },
    )
  })
})
