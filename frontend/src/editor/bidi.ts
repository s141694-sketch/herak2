import { Extension } from '@tiptap/core'
import type { Node as PMNode } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

/**
 * Per-block text direction, computed from the first strong character and
 * applied as a view-only decoration (phase 0 finding: dir="auto" on list
 * items is defeated by children carrying their own dir).
 */

const RTL = /[֐-ࣿיִ-﷿ﹰ-﻿]/u
const STRONG = /\p{L}/u
const BLOCKS = new Set(['paragraph', 'heading', 'listItem', 'blockquote', 'codeBlock'])

export function directionOf(text: string): 'rtl' | 'ltr' | null {
  for (const ch of text) {
    if (RTL.test(ch)) return 'rtl'
    if (STRONG.test(ch)) return 'ltr'
  }
  return null
}

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

export const BidiDirection = Extension.create({
  name: 'bidiDirection',
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey('bidiDirection'),
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
