import * as Y from 'yjs'

import { blockFragment } from './schema'

/**
 * Comment anchors on live draft text (task 0.6).
 *
 * An anchor is a pair of Yjs relative positions inside one block plus the
 * quoted text. `start` is right-associated and `end` left-associated, so text
 * inserted exactly at either boundary stays outside the range.
 */
export interface Anchor {
  block_key: string
  start: Y.RelativePosition
  end: Y.RelativePosition
  quoted: string
}

export interface Resolution {
  status: 'intact' | 'changed' | 'orphaned'
  /** Text currently inside the range, when it still exists. */
  current?: string
  from?: number
  to?: number
  reason?: string
}

export function createAnchor(_doc: Y.Doc, blockKey: string, text: Y.XmlText, from: number, to: number): Anchor {
  if (to <= from) throw new Error('empty anchor range')
  return {
    block_key: blockKey,
    start: Y.createRelativePositionFromTypeIndex(text, from, 0),
    end: Y.createRelativePositionFromTypeIndex(text, to, -1),
    quoted: text.toString().slice(from, to),
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function belongsToBlock(doc: Y.Doc, type: Y.AbstractType<any>, blockKey: string): boolean {
  const fragment = blockFragment(doc, blockKey)
  let current: Y.AbstractType<any> | null = type
  while (current) {
    if (current === fragment) return true
    current = current.parent as Y.AbstractType<any> | null
  }
  return false
}

export function resolveAnchor(doc: Y.Doc, anchor: Anchor): Resolution {
  const start = Y.createAbsolutePositionFromRelativePosition(anchor.start, doc)
  const end = Y.createAbsolutePositionFromRelativePosition(anchor.end, doc)
  if (!start || !end) return { status: 'orphaned', reason: 'position no longer exists in this document' }
  if (start.type !== end.type || !(start.type instanceof Y.XmlText)) return { status: 'orphaned', reason: 'boundaries no longer share a text node' }
  const text = start.type as Y.XmlText
  if (text._item?.deleted) return { status: 'orphaned', reason: 'text node deleted' }
  if (!belongsToBlock(doc, text, anchor.block_key)) return { status: 'orphaned', reason: 'text node left the block' }
  if (end.index <= start.index) return { status: 'orphaned', reason: 'anchored text deleted' }
  const current = text.toString().slice(start.index, end.index)
  return { status: current === anchor.quoted ? 'intact' : 'changed', current, from: start.index, to: end.index }
}

function toBase64(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString('base64')
}

function fromBase64(value: string): Uint8Array {
  return new Uint8Array(Buffer.from(value, 'base64'))
}

/** Storable form: what the Comment row would hold. */
export function serializeAnchor(anchor: Anchor): string {
  return JSON.stringify({
    block_key: anchor.block_key,
    start: toBase64(Y.encodeRelativePosition(anchor.start)),
    end: toBase64(Y.encodeRelativePosition(anchor.end)),
    quoted: anchor.quoted,
  })
}

export function deserializeAnchor(stored: string): Anchor {
  const parsed = JSON.parse(stored) as { block_key: string; start: string; end: string; quoted: string }
  return {
    block_key: parsed.block_key,
    start: Y.decodeRelativePosition(fromBase64(parsed.start)),
    end: Y.decodeRelativePosition(fromBase64(parsed.end)),
    quoted: parsed.quoted,
  }
}

function textsIn(fragment: Y.XmlFragment): Y.XmlText[] {
  const out: Y.XmlText[] = []
  const walk = (node: Y.XmlFragment | Y.XmlElement) => {
    for (const child of node.toArray()) {
      if (child instanceof Y.XmlText) out.push(child)
      else if (child instanceof Y.XmlElement) walk(child)
    }
  }
  walk(fragment)
  return out
}

/** Fallback for documents whose Yjs history does not contain the anchor's items. */
export function reanchorByText(doc: Y.Doc, anchor: Anchor): { status: 'reanchored' | 'ambiguous' | 'not_found'; anchor?: Anchor } {
  const hits: Array<{ text: Y.XmlText; from: number }> = []
  for (const text of textsIn(blockFragment(doc, anchor.block_key))) {
    const value = text.toString()
    let from = value.indexOf(anchor.quoted)
    while (from !== -1) {
      hits.push({ text, from })
      from = value.indexOf(anchor.quoted, from + 1)
    }
  }
  if (hits.length === 0) return { status: 'not_found' }
  if (hits.length > 1) return { status: 'ambiguous' }
  const [{ text, from }] = hits
  return { status: 'reanchored', anchor: createAnchor(doc, anchor.block_key, text, from, from + anchor.quoted.length) }
}
