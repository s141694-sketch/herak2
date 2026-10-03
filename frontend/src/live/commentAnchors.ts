import type { Editor } from '@tiptap/core'
import { absolutePositionToRelativePosition, relativePositionToAbsolutePosition, ySyncPluginKey } from '@tiptap/y-tiptap'
import { fromBase64, toBase64 } from 'lib0/buffer'
import * as Y from 'yjs'

/**
 * Comment anchors on the live document (phase 0 design): the start is right-associated and
 * the end left-associated, so text typed exactly at either edge stays outside the quote.
 */

export interface StoredAnchor {
  start: string
  end: string
}

export type AnchorStatus = 'intact' | 'changed' | 'orphaned'

export interface Resolved {
  status: AnchorStatus
  from?: number
  to?: number
  current?: string
}

function mappingOf(editor: Editor) {
  return ySyncPluginKey.getState(editor.state)?.binding?.mapping
}

export function anchorFromSelection(editor: Editor, fragment: Y.XmlFragment, doc: Y.Doc): { anchor: StoredAnchor; quoted: string } | null {
  const { from, to } = editor.state.selection
  const mapping = mappingOf(editor)
  if (from === to || !mapping) return null
  const leftStart = absolutePositionToRelativePosition(from, fragment, mapping)
  const absolute = Y.createAbsolutePositionFromRelativePosition(leftStart, doc)
  const start = absolute ? Y.createRelativePositionFromTypeIndex(absolute.type, absolute.index, 0) : leftStart
  const end = absolutePositionToRelativePosition(to, fragment, mapping)
  return {
    anchor: { start: toBase64(Y.encodeRelativePosition(start)), end: toBase64(Y.encodeRelativePosition(end)) },
    quoted: editor.state.doc.textBetween(from, to, '\n'),
  }
}

export function resolveInEditor(editor: Editor, fragment: Y.XmlFragment, doc: Y.Doc, anchor: StoredAnchor, quoted: string): Resolved {
  const mapping = mappingOf(editor)
  if (!mapping) return { status: 'orphaned' }
  try {
    const from = relativePositionToAbsolutePosition(doc, fragment, Y.decodeRelativePosition(fromBase64(anchor.start)), mapping)
    const to = relativePositionToAbsolutePosition(doc, fragment, Y.decodeRelativePosition(fromBase64(anchor.end)), mapping)
    if (from === null || to === null || to <= from) return { status: 'orphaned' }
    const current = editor.state.doc.textBetween(from, to, '\n')
    return { status: current === quoted ? 'intact' : 'changed', from, to, current }
  } catch {
    return { status: 'orphaned' }
  }
}
