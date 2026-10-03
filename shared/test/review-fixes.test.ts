/** Phase 3 review findings in the shared document code, each reproduced as a test. */
import { describe, expect, it } from 'vitest'
import * as Y from 'yjs'

import { createAnchor, plainText, reanchorByText, resolveAnchor } from '../src/anchors'
import { editorSchema, isSafeHref } from '../src/editor'
import { hydrate, hydrateStable, materialize, setBlockContent, stableClientId, UnrepresentableContent } from '../src/materialize'
import { addBlock, addNode, DocumentRuleError, MAX_TITLE_LENGTH, renameNode } from '../src/operations'
import { blockFragment } from '../src/schema'

const element = (attrs: Record<string, string>) => ({ getAttribute: (name: string) => attrs[name] ?? null }) as unknown as HTMLElement

describe('pasted links', () => {
  const parse = (attrs: Record<string, string>) => {
    const rule = editorSchema.marks.link.spec.parseDOM![0] as { getAttrs: (el: HTMLElement) => unknown }
    return rule.getAttrs(element(attrs))
  }

  it.each(['javascript:alert(1)', '#_Toc123456', '/docs/x', 'www.example.com', 'tel:+96899999999', 'ftp://host/file'])(
    'refuses %s, which the server would reject',
    (href) => expect(parse({ href })).toBe(false),
  )

  it('keeps only a safe href and the editor’s own attributes', () => {
    const attrs = parse({ href: 'https://example.com/a', class: 'x'.repeat(150), title: '2024', target: '_top', rel: 'opener' })
    expect(attrs).toEqual({ href: 'https://example.com/a' })
    expect(editorSchema.mark('link', attrs as Record<string, unknown>).attrs).toEqual({
      href: 'https://example.com/a', target: '_blank', rel: 'noopener noreferrer nofollow', class: null, title: null,
    })
    expect(isSafeHref('  MAILTO:a@b.om')).toBe(true)
    expect(isSafeHref(`https://e.com/${'a'.repeat(2000)}`)).toBe(false)
  })
})

function sample() {
  const doc = new Y.Doc()
  const node = addNode(doc, { parent: null, title: 'الوحدة', key: 'n1' }, 4)
  addBlock(doc, { node_key: node, type: 'objective', key: 'b1' })
  setBlockContent(doc, 'b1', {
    type: 'doc',
    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'يصف', marks: [{ type: 'bold' }] }, { type: 'text', text: ' المتدرب خطوات الإجراء' }] }],
  })
  return materialize(doc)
}

const textOf = (doc: Y.Doc) => (blockFragment(doc, 'b1').get(0) as Y.XmlElement).get(0) as Y.XmlText

describe('documents rebuilt from rows', () => {
  it('are identical every time, so two rebuilds merge without conflict', () => {
    const rows = sample()
    const first = hydrateStable(rows)
    const second = hydrateStable(rows)
    expect(Y.encodeStateVector(first)).toEqual(Y.encodeStateVector(second))
    expect(stableClientId(rows)).toBe(stableClientId(JSON.parse(JSON.stringify(rows))))
    Y.applyUpdate(first, Y.encodeStateAsUpdate(second))
    expect(materialize(first)).toEqual(rows)
  })

  it('keep a reconnecting client’s edit and its comment anchor after the server rebuilds them', () => {
    const rows = sample()
    const client = hydrateStable(rows)
    const from = plainText(textOf(client)).indexOf('خطوات')
    const anchor = createAnchor('b1', textOf(client), from, from + 'خطوات الإجراء'.length)
    textOf(client).insert(plainText(textOf(client)).length, ' بدقة')
    const server = hydrateStable(rows)
    Y.applyUpdate(server, Y.encodeStateAsUpdate(client))
    expect(JSON.stringify(materialize(server).blocks[0].content)).toContain('بدقة')
    expect(resolveAnchor(server, anchor)).toMatchObject({ status: 'intact', current: 'خطوات الإجراء' })
    const plain = new Y.Doc()
    hydrate(rows, plain)
    expect(resolveAnchor(plain, anchor).status).toBe('orphaned')
  })
})

describe('comment anchors on formatted text', () => {
  it('quote the characters, not the markup, and stay intact when formatting changes outside them', () => {
    const doc = hydrateStable(sample())
    const text = textOf(doc)
    expect(plainText(text)).toBe('يصف المتدرب خطوات الإجراء')
    const from = plainText(text).indexOf('خطوات')
    const anchor = createAnchor('b1', text, from, from + 'خطوات الإجراء'.length)
    expect(anchor.quoted).toBe('خطوات الإجراء')
    text.format(4, 7, { italic: {} })
    expect(resolveAnchor(doc, anchor)).toMatchObject({ status: 'intact', current: 'خطوات الإجراء' })
    const rebuilt = hydrate(materialize(doc))
    const found = reanchorByText(rebuilt, anchor)
    expect(found.status).toBe('reanchored')
    expect(resolveAnchor(rebuilt, found.anchor!)).toMatchObject({ status: 'intact' })
    expect(reanchorByText(rebuilt, { ...anchor, quoted: '' }).status).toBe('not_found')
  })
})

describe('materialize', () => {
  it('fails on content the schema cannot represent instead of deleting it from the live document', () => {
    const doc = hydrateStable(sample())
    blockFragment(doc, 'b1').insert(0, [new Y.XmlElement('image')])
    const before = Y.encodeStateAsUpdate(doc)
    expect(() => materialize(doc)).toThrow(UnrepresentableContent)
    expect(Y.encodeStateAsUpdate(doc)).toEqual(before)
    expect(blockFragment(doc, 'b1').length).toBe(2)
  })
})

describe('node titles', () => {
  it('stop at the server’s limit, counted in characters', () => {
    const doc = new Y.Doc()
    const fits = '😀'.repeat(MAX_TITLE_LENGTH)
    const key = addNode(doc, { parent: null, title: fits }, 4)
    expect(() => renameNode(doc, key, `${fits}x`)).toThrow(DocumentRuleError)
    expect(() => addNode(doc, { parent: null, title: 'ب'.repeat(MAX_TITLE_LENGTH + 1) }, 4)).toThrow(
      expect.objectContaining({ code: 'node_title_too_long' }),
    )
  })
})
