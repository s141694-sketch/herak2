import * as Y from 'yjs'

import { plainText } from './anchors'
import { setBlockContent } from './materialize'
import { addBlock, addLink, addNode, DocumentRuleError } from './operations'
import { blocksOf } from './schema'

/**
 * Writing an accepted AI suggestion into the live document (task 4.8). The author's own editor applies it, as an
 * ordinary edit by that person; the server only records the decision.
 */

/** Elements whose text the server puts on a line of its own (apps.programs.content.plain_text). */
const LINES = new Set(['paragraph', 'heading', 'listItem', 'blockquote', 'codeBlock'])

/** A block's text as the server reads it: plain characters, one line per paragraph or list item. */
export function blockPlainText(doc: Y.Doc, blockKey: string): string {
  const fragment = blocksOf(doc).get(blockKey)?.get('content') as Y.XmlFragment | undefined
  if (!fragment) return ''
  const lines: string[] = []
  let current = ''
  const flush = () => {
    if (current.trim()) lines.push(current.trim())
    current = ''
  }
  const walk = (node: Y.XmlElement | Y.XmlText | Y.XmlHook) => {
    if (node instanceof Y.XmlText) current += plainText(node)
    else if (node instanceof Y.XmlElement) {
      const line = LINES.has(node.nodeName)
      if (line) flush()
      node.toArray().forEach(walk)
      if (line) flush()
    }
  }
  fragment.toArray().forEach(walk)
  flush()
  return lines.join('\n')
}

const normalized = (text: string) => text.split(/\s+/).filter(Boolean).join(' ')

const paragraphs = (text: string) => ({
  type: 'doc',
  content: text
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => ({ type: 'paragraph', content: [{ type: 'text', text: line.trim() }] })),
})

/**
 * Replaces an objective's text with its rewrite, only if the text is still the one the rewrite was made for:
 * 'changed' when someone edited it since, 'missing' when the block is gone.
 */
export function applyRewrite(doc: Y.Doc, blockKey: string, original: string, rewrite: string): 'applied' | 'changed' | 'missing' {
  if (!blocksOf(doc).has(blockKey)) return 'missing'
  if (normalized(blockPlainText(doc, blockKey)) !== normalized(original)) return 'changed'
  setBlockContent(doc, blockKey, paragraphs(rewrite))
  return 'applied'
}

export interface OutlineSuggestion {
  nodes: Array<{ ref: string; parent: string; title: string }>
  objectives: Array<{ node: string; text: string; competency_key: string | null }>
}

function write(doc: Y.Doc, outline: OutlineSuggestion, levelCount: number) {
  const keys = new Map<string, string>()
  for (const node of outline.nodes) {
    const parent = node.parent ? keys.get(node.parent) : null
    if (parent === undefined) throw new DocumentRuleError('node_parent_invalid')
    keys.set(node.ref, addNode(doc, { parent, title: node.title }, levelCount))
  }
  for (const objective of outline.objectives) {
    const nodeKey = keys.get(objective.node)
    if (!nodeKey) throw new DocumentRuleError('block_node_invalid')
    const block = addBlock(doc, { node_key: nodeKey, type: 'objective' })
    setBlockContent(doc, block, paragraphs(objective.text))
    if (objective.competency_key) addLink(doc, { kind: 'objective_competency', source_key: block, competency_key: objective.competency_key })
  }
  return { nodes: outline.nodes.length, objectives: outline.objectives.length }
}

/**
 * Adds an outline's nodes (after the top-level nodes already there), its objectives and their links to the
 * competencies, as one change. It is tried on a copy first, so a rule that refuses any part leaves the
 * document untouched (a Yjs transaction cannot be rolled back).
 */
export function applyOutline(doc: Y.Doc, outline: OutlineSuggestion, levelCount: number): { nodes: number; objectives: number } {
  const trial = new Y.Doc()
  Y.applyUpdate(trial, Y.encodeStateAsUpdate(doc))
  write(trial, outline, levelCount)
  trial.destroy()
  let counts = { nodes: 0, objectives: 0 }
  doc.transact(() => {
    counts = write(doc, outline, levelCount)
  })
  return counts
}
