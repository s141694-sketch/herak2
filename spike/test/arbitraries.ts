import fc from 'fast-check'

import type { BlockType } from '../src/schema'
import { BLOCK_TYPES } from '../src/schema'
import type { ProseMirrorJSON } from '../src/materialize'

/** Shared fast-check generators for tasks 0.4 and 0.5. Arabic-heavy by design. */

const ARABIC_LETTERS = range(0x0621, 0x064a)
const TASHKEEL = range(0x064b, 0x0652)
const ARABIC_INDIC_DIGITS = range(0x0660, 0x0669)
const EXTENDED_DIGITS = range(0x06f0, 0x06f9)
const PRESENTATION_FORMS = [0xfe8d, 0xfe8e, 0xfeef, 0xfef0, 0xfefb, 0xfefc, 0xfb56, 0xfb7a]
const ARABIC_PUNCT = [0x060c, 0x061b, 0x061f, 0x066a, 0x066b, 0x066c, 0x0640]
const LATIN = [...range(0x41, 0x5a), ...range(0x61, 0x7a)]
const WESTERN_DIGITS = range(0x30, 0x39)
const ASCII_PUNCT = [0x20, 0x2e, 0x2c, 0x3f, 0x21, 0x3a, 0x28, 0x29, 0x25, 0x2d, 0x2f, 0x22, 0x27]
const BIDI_CONTROLS = [0x200e, 0x200f, 0x202a, 0x202b, 0x202c, 0x202d, 0x202e, 0x2066, 0x2067, 0x2068, 0x2069, 0x200c, 0x200d]
const QUOTES = [0x00ab, 0x00bb, 0x201c, 0x201d]
const EMOJI = ['😀', '🇴🇲', '👍🏽']

function range(from: number, to: number): number[] {
  const out: number[] = []
  for (let c = from; c <= to; c += 1) out.push(c)
  return out
}

const codePointArb = fc.oneof(
  { weight: 10, arbitrary: fc.constantFrom(...ARABIC_LETTERS) },
  { weight: 3, arbitrary: fc.constantFrom(...TASHKEEL) },
  { weight: 3, arbitrary: fc.constantFrom(0x20) },
  { weight: 2, arbitrary: fc.constantFrom(...ARABIC_INDIC_DIGITS, ...EXTENDED_DIGITS, ...WESTERN_DIGITS) },
  { weight: 2, arbitrary: fc.constantFrom(...ARABIC_PUNCT, ...ASCII_PUNCT, ...QUOTES) },
  { weight: 2, arbitrary: fc.constantFrom(...LATIN) },
  { weight: 1, arbitrary: fc.constantFrom(...BIDI_CONTROLS) },
  { weight: 1, arbitrary: fc.constantFrom(...PRESENTATION_FORMS) },
)

/** Non-empty text with Arabic, diacritics, digits, Latin, punctuation, bidi controls and emoji. */
export const textArb: fc.Arbitrary<string> = fc
  .tuple(fc.array(codePointArb, { minLength: 1, maxLength: 24 }), fc.option(fc.constantFrom(...EMOJI), { nil: '' }))
  .map(([cps, emoji]) => String.fromCodePoint(...cps) + emoji)

const marksArb = fc.oneof(
  { weight: 5, arbitrary: fc.constant(undefined) },
  { weight: 1, arbitrary: fc.constant([{ type: 'code' }]) },
  { weight: 3, arbitrary: fc.subarray([{ type: 'bold' }, { type: 'italic' }, { type: 'strike' }], { minLength: 1 }) },
)

const textNodeArb = fc.tuple(textArb, marksArb).map(([text, marks]) => (marks ? { type: 'text', text, marks } : { type: 'text', text }))

const inlineArb = fc.oneof({ weight: 8, arbitrary: textNodeArb }, { weight: 1, arbitrary: fc.constant({ type: 'hardBreak' }) })

const inlinesArb = fc.array(inlineArb, { minLength: 0, maxLength: 5 })

const paragraphArb = inlinesArb.map((content) => (content.length ? { type: 'paragraph', content } : { type: 'paragraph' }))

const headingArb = fc
  .tuple(fc.integer({ min: 1, max: 6 }), fc.array(textNodeArb, { minLength: 1, maxLength: 3 }))
  .map(([level, content]) => ({ type: 'heading', attrs: { level }, content }))

const codeBlockArb = fc
  .array(fc.tuple(textArb, fc.constantFrom('', '\n')), { minLength: 0, maxLength: 3 })
  .map((parts) => {
    const text = parts.map(([t, nl]) => t + nl).join('')
    return text ? { type: 'codeBlock', attrs: { language: null }, content: [{ type: 'text', text }] } : { type: 'codeBlock', attrs: { language: null } }
  })

function listArb(depth: number): fc.Arbitrary<ProseMirrorJSON> {
  const item: fc.Arbitrary<ProseMirrorJSON> =
    depth <= 0
      ? paragraphArb.map((p) => ({ type: 'listItem', content: [p] }))
      : fc.tuple(paragraphArb, fc.option(listArb(depth - 1), { nil: null })).map(([p, nested]) => ({
          type: 'listItem',
          content: nested ? [p, nested] : [p],
        }))
  return fc.oneof(
    fc.array(item, { minLength: 1, maxLength: 3 }).map((content) => ({ type: 'bulletList', content })),
    fc
      .tuple(fc.integer({ min: 1, max: 20 }), fc.array(item, { minLength: 1, maxLength: 3 }))
      .map(([start, content]) => ({ type: 'orderedList', attrs: { start }, content })),
  )
}

const blockNodeArb: fc.Arbitrary<ProseMirrorJSON> = fc.oneof(
  { weight: 6, arbitrary: paragraphArb },
  { weight: 2, arbitrary: headingArb },
  { weight: 2, arbitrary: listArb(2) },
  { weight: 1, arbitrary: fc.array(paragraphArb, { minLength: 1, maxLength: 2 }).map((content) => ({ type: 'blockquote', content })) },
  { weight: 1, arbitrary: codeBlockArb },
  { weight: 1, arbitrary: fc.constant({ type: 'horizontalRule' }) },
)

/** A TipTap/ProseMirror document as the editor would emit it (StarterKit schema: at least one block). */
export const richDocArb: fc.Arbitrary<ProseMirrorJSON> = fc
  .array(blockNodeArb, { minLength: 1, maxLength: 6 })
  .map((content) => ({ type: 'doc', content }))

export interface GeneratedNode {
  key: string
  parent: string | null
  order: number
  deleted: boolean
}

export interface GeneratedBlock {
  key: string
  node_key: string
  type: BlockType
  deleted: boolean
  content: ProseMirrorJSON
}

export interface GeneratedStructure {
  nodes: GeneratedNode[]
  blocks: GeneratedBlock[]
}

export const MAX_DEPTH = 4 // five levels: 0..4

/** A tree of up to `maxNodes` nodes within five levels, each with 0..3 blocks. */
export function structureArb(maxNodes = 30): fc.Arbitrary<GeneratedStructure> {
  return fc
    .tuple(
      fc.integer({ min: 1, max: maxNodes }),
      fc.infiniteStream(fc.tuple(fc.nat(), fc.integer({ min: -3, max: 3 }), fc.boolean())),
      fc.infiniteStream(fc.tuple(fc.integer({ min: 0, max: 3 }), fc.constantFrom(...BLOCK_TYPES), fc.boolean())),
      fc.infiniteStream(richDocArb),
      fc.string({ minLength: 1, maxLength: 6, unit: 'grapheme-ascii' }),
    )
    .map(([count, nodeStream, blockStream, docStream, salt]) => {
      const nodes: GeneratedNode[] = []
      const depth = new Map<string, number>()
      const nodeIt = nodeStream[Symbol.iterator]()
      for (let i = 0; i < count; i += 1) {
        const [pick, order, deleted] = nodeIt.next().value as [number, number, boolean]
        const key = `n${i}-${salt}`
        const candidates = nodes.filter((n) => depth.get(n.key)! < MAX_DEPTH)
        const parent = i === 0 || pick % 5 === 0 || !candidates.length ? null : candidates[pick % candidates.length].key
        depth.set(key, parent === null ? 0 : depth.get(parent)! + 1)
        nodes.push({ key, parent, order, deleted })
      }
      const blocks: GeneratedBlock[] = []
      const blockIt = blockStream[Symbol.iterator]()
      const docIt = docStream[Symbol.iterator]()
      for (const node of nodes) {
        const [n] = blockIt.next().value as [number, BlockType, boolean]
        for (let j = 0; j < n; j += 1) {
          const [, type, deleted] = blockIt.next().value as [number, BlockType, boolean]
          blocks.push({ key: `b${blocks.length}-${salt}`, node_key: node.key, type, deleted, content: docIt.next().value as ProseMirrorJSON })
        }
      }
      return { nodes, blocks }
    })
}
