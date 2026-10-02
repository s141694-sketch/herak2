import fc from 'fast-check'

import { materialize, type ProseMirrorJSON } from '../src/materialize'

/** Generators heavy in Arabic: letters, diacritics, Arabic-Indic digits, punctuation, bidi controls, emoji. */
const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => from + i)

const codePoint = fc.oneof(
  { weight: 10, arbitrary: fc.constantFrom(...range(0x0621, 0x064a)) },
  { weight: 3, arbitrary: fc.constantFrom(...range(0x064b, 0x0652)) },
  { weight: 3, arbitrary: fc.constant(0x20) },
  { weight: 2, arbitrary: fc.constantFrom(...range(0x0660, 0x0669), ...range(0x06f0, 0x06f9), ...range(0x30, 0x39)) },
  { weight: 2, arbitrary: fc.constantFrom(0x060c, 0x061b, 0x061f, 0x066a, 0x0640, 0x2e, 0x2c, 0x28, 0x29, 0x25, 0xab, 0xbb, 0x201c, 0x201d) },
  { weight: 2, arbitrary: fc.constantFrom(...range(0x41, 0x5a), ...range(0x61, 0x7a)) },
  { weight: 1, arbitrary: fc.constantFrom(0x200e, 0x200f, 0x202a, 0x202b, 0x202c, 0x2066, 0x2069, 0x200c, 0x200d) },
  { weight: 1, arbitrary: fc.constantFrom(0xfe8d, 0xfefb, 0xfb56) },
)

export const textArb: fc.Arbitrary<string> = fc
  .tuple(fc.array(codePoint, { minLength: 1, maxLength: 24 }), fc.option(fc.constantFrom('😀', '🇴🇲', '👍🏽'), { nil: '' }))
  .map(([cps, emoji]) => String.fromCodePoint(...cps) + emoji)

const marks = fc.oneof(
  { weight: 5, arbitrary: fc.constant(undefined) },
  { weight: 1, arbitrary: fc.constant([{ type: 'code' }]) },
  { weight: 3, arbitrary: fc.subarray([{ type: 'bold' }, { type: 'italic' }, { type: 'strike' }, { type: 'underline' }], { minLength: 1 }) },
)
const textNode = fc.tuple(textArb, marks).map(([text, m]) => (m ? { type: 'text', text, marks: m } : { type: 'text', text }))
const inline = fc.oneof({ weight: 8, arbitrary: textNode }, { weight: 1, arbitrary: fc.constant({ type: 'hardBreak' }) })
const paragraph = fc.array(inline, { maxLength: 5 }).map((content) => (content.length ? { type: 'paragraph', content } : { type: 'paragraph' }))
const heading = fc.tuple(fc.integer({ min: 1, max: 6 }), fc.array(textNode, { minLength: 1, maxLength: 3 })).map(([level, content]) => ({ type: 'heading', attrs: { level }, content }))

function list(depth: number): fc.Arbitrary<ProseMirrorJSON> {
  const item: fc.Arbitrary<ProseMirrorJSON> =
    depth <= 0
      ? paragraph.map((p) => ({ type: 'listItem', content: [p] }))
      : fc.tuple(paragraph, fc.option(list(depth - 1), { nil: null })).map(([p, nested]) => ({ type: 'listItem', content: nested ? [p, nested] : [p] }))
  return fc.oneof(
    fc.array(item, { minLength: 1, maxLength: 3 }).map((content) => ({ type: 'bulletList', content })),
    fc.tuple(fc.integer({ min: 1, max: 20 }), fc.array(item, { minLength: 1, maxLength: 3 })).map(([start, content]) => ({ type: 'orderedList', attrs: { start, type: null }, content })),
  )
}

const blockNode: fc.Arbitrary<ProseMirrorJSON> = fc.oneof(
  { weight: 6, arbitrary: paragraph },
  { weight: 2, arbitrary: heading },
  { weight: 2, arbitrary: list(2) },
  { weight: 1, arbitrary: fc.array(paragraph, { minLength: 1, maxLength: 2 }).map((content) => ({ type: 'blockquote', content })) },
  { weight: 1, arbitrary: fc.constant({ type: 'horizontalRule' }) },
)

export const richDocArb: fc.Arbitrary<ProseMirrorJSON> = fc.array(blockNode, { minLength: 1, maxLength: 6 }).map((content) => ({ type: 'doc', content }))

export const BLOCK_TYPE_ARB = fc.constantFrom('objective', 'content', 'activity', 'assessment', 'reference') as fc.Arbitrary<
  'objective' | 'content' | 'activity' | 'assessment' | 'reference'
>

export type Materialized = ReturnType<typeof materialize>
