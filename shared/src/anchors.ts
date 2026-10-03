import { fromBase64, toBase64 } from 'lib0/buffer'
import * as Y from 'yjs'

import { blocksOf } from './schema'

/**
 * Comment anchors (phase 0, task 0.6). The start is right-associated and the
 * end left-associated, so text typed exactly at either boundary stays outside.
 * Anchors live as long as the Yjs items they point at: a new draft copies the
 * Yjs state (D2), and a document rebuilt from rows needs reanchorByText().
 */

export interface Anchor {
  block_key: string
  start: Y.RelativePosition
  end: Y.RelativePosition
  quoted: string
}

export type AnchorStatus = 'intact' | 'changed' | 'orphaned'

export interface Resolution {
  status: AnchorStatus
  current?: string
  from?: number
  to?: number
  text?: Y.XmlText
}

/** The characters of a text, without the formatting markup ``toString()`` adds around marked runs. */
export function plainText(text: Y.XmlText): string {
  return text
    .toDelta()
    .map((part: { insert: unknown }) => (typeof part.insert === 'string' ? part.insert : ''))
    .join('')
}

export function createAnchor(blockKey: string, text: Y.XmlText, from: number, to: number): Anchor {
  if (to <= from) throw new Error('empty anchor range')
  return {
    block_key: blockKey,
    start: Y.createRelativePositionFromTypeIndex(text, from, 0),
    end: Y.createRelativePositionFromTypeIndex(text, to, -1),
    quoted: plainText(text).slice(from, to),
  }
}

function insideBlock(doc: Y.Doc, type: Y.AbstractType<any>, blockKey: string): boolean {
  const fragment = blocksOf(doc).get(blockKey)?.get('content')
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
  if (!start || !end || start.type !== end.type || !(start.type instanceof Y.XmlText)) return { status: 'orphaned' }
  const text = start.type as Y.XmlText
  if (text._item?.deleted || !insideBlock(doc, text, anchor.block_key) || end.index <= start.index) return { status: 'orphaned' }
  const current = plainText(text).slice(start.index, end.index)
  return { status: current === anchor.quoted ? 'intact' : 'changed', current, from: start.index, to: end.index, text }
}

export interface StoredAnchor {
  block_key: string
  start: string
  end: string
  quoted: string
}

export function serializeAnchor(anchor: Anchor): StoredAnchor {
  return {
    block_key: anchor.block_key,
    start: toBase64(Y.encodeRelativePosition(anchor.start)),
    end: toBase64(Y.encodeRelativePosition(anchor.end)),
    quoted: anchor.quoted,
  }
}

export function deserializeAnchor(stored: StoredAnchor): Anchor {
  return {
    block_key: stored.block_key,
    start: Y.decodeRelativePosition(fromBase64(stored.start)),
    end: Y.decodeRelativePosition(fromBase64(stored.end)),
    quoted: stored.quoted,
  }
}

export function textsOf(fragment: Y.XmlFragment): Y.XmlText[] {
  const found: Y.XmlText[] = []
  const walk = (node: Y.XmlFragment | Y.XmlElement) => {
    for (const child of node.toArray()) {
      if (child instanceof Y.XmlText) found.push(child)
      else if (child instanceof Y.XmlElement) walk(child)
    }
  }
  walk(fragment)
  return found
}

/** Fallback when the Yjs items are gone: find the quoted text once, and only once, in the same block. */
export function reanchorByText(doc: Y.Doc, anchor: Anchor): { status: 'reanchored' | 'ambiguous' | 'not_found'; anchor?: Anchor } {
  const fragment = blocksOf(doc).get(anchor.block_key)?.get('content') as Y.XmlFragment | undefined
  if (!fragment || !anchor.quoted) return { status: 'not_found' }
  const hits: Array<{ text: Y.XmlText; from: number }> = []
  for (const text of textsOf(fragment)) {
    const value = plainText(text)
    for (let from = value.indexOf(anchor.quoted); from !== -1; from = value.indexOf(anchor.quoted, from + 1)) hits.push({ text, from })
  }
  if (hits.length === 0) return { status: 'not_found' }
  if (hits.length > 1) return { status: 'ambiguous' }
  const [{ text, from }] = hits
  return { status: 'reanchored', anchor: createAnchor(anchor.block_key, text, from, from + anchor.quoted.length) }
}
