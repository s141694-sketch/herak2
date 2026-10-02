import { Extension } from '@tiptap/core'
import type { Node as PMNode } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

/**
 * Per-block direction (task 0.7).
 *
 * dir="auto" is not enough: the HTML algorithm ignores descendants that carry
 * their own dir, so a list item whose paragraph has dir="auto" resolves to LTR
 * and its bullet lands on the wrong side. This plugin computes the direction of
 * every block from its first strong character and applies it as a view-only
 * node decoration, so nothing is written into the shared document.
 */

const RTL = /[֐-ࣿיִ-﷿ﹰ-﻿]/u
const STRONG = /[\p{L}]/u

export function directionOf(text: string): 'rtl' | 'ltr' | null {
  for (const ch of text) {
    if (RTL.test(ch)) return 'rtl'
    if (STRONG.test(ch)) return 'ltr'
  }
  return null
}

const BLOCKS = new Set(['paragraph', 'heading', 'listItem', 'blockquote', 'codeBlock'])

function decorate(doc: PMNode): DecorationSet {
  const decorations: Decoration[] = []
  doc.descendants((node, pos) => {
    if (!BLOCKS.has(node.type.name)) return true
    const dir = directionOf(node.textContent)
    if (dir) decorations.push(Decoration.node(pos, pos + node.nodeSize, { dir }))
    return true
  })
  return DecorationSet.create(doc, decorations)
}

export const BidiAuto = Extension.create({
  name: 'bidiAuto',
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey('bidiAuto'),
        state: {
          init: (_config, state) => decorate(state.doc),
          apply: (tr, old) => (tr.docChanged ? decorate(tr.doc) : old),
        },
        props: {
          decorations(state) {
            return this.getState(state)
          },
        },
      }),
    ]
  },
})
