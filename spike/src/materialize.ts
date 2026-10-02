import { getSchema } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import { prosemirrorJSONToYXmlFragment, yXmlFragmentToProseMirrorRootNode } from '@tiptap/y-tiptap'
import * as Y from 'yjs'

import {
  type BlockType,
  blockFragment,
  blocksMap,
  createBlock,
  createNode,
  nodesMap,
  softDeleteBlock,
  softDeleteNode,
} from './schema'

/**
 * Conversion between the live Y.Doc and flat rows (task 0.3).
 *
 * Rows are what the backend stores per version. `materialize` is pure with
 * respect to the document (no mutation) and deterministic: two replicas with
 * the same Yjs state produce identical rows, including after repairs.
 */

/** The ProseMirror schema shared by every block editor. DOM-free, so it runs in Node. */
export const editorSchema = getSchema([StarterKit.configure({ undoRedo: false })])

export type ProseMirrorJSON = Record<string, unknown>

export interface NodeRow {
  node_key: string
  parent_key: string | null
  /** Depth computed from parent links (authoritative), not the stored level. */
  level: number
  order: number
  deleted: boolean
}

export interface BlockRow {
  block_key: string
  node_key: string
  type: BlockType
  deleted: boolean
  content: ProseMirrorJSON
}

export type Issue =
  | { kind: 'orphan'; node_keys: string[]; detail: string }
  | { kind: 'cycle'; node_keys: string[]; detail: string }
  | { kind: 'dangling_block'; block_keys: string[]; detail: string }

export interface Rows {
  nodes: NodeRow[]
  blocks: BlockRow[]
  issues: Issue[]
}

const ROOT = '\u0000root'

function compareSiblings(a: { order: number; node_key: string }, b: { order: number; node_key: string }): number {
  if (a.order !== b.order) return a.order - b.order
  return a.node_key < b.node_key ? -1 : a.node_key > b.node_key ? 1 : 0
}

/** Reads raw parent links and repairs orphans and cycles with a deterministic rule. */
function resolveTree(doc: Y.Doc): { parentOf: Map<string, string | null>; issues: Issue[] } {
  const nodes = nodesMap(doc)
  const parentOf = new Map<string, string | null>()
  const issues: Issue[] = []

  const orphans: string[] = []
  nodes.forEach((node, key) => {
    const parent = (node.get('parent') as string | null) ?? null
    if (parent !== null && !nodes.has(parent)) {
      orphans.push(key)
      parentOf.set(key, null)
    } else {
      parentOf.set(key, parent)
    }
  })
  if (orphans.length) {
    orphans.sort()
    issues.push({ kind: 'orphan', node_keys: orphans, detail: 'parent missing; reattached to root' })
  }

  // Cycle detection: walk up from every node; a node seen twice on one walk is in a cycle.
  // Repair rule: the lexicographically smallest key of the cycle is reattached to root.
  const resolved = new Set<string>()
  for (const start of [...parentOf.keys()].sort()) {
    const path: string[] = []
    const onPath = new Set<string>()
    let current: string | null = start
    while (current !== null && !resolved.has(current)) {
      if (onPath.has(current)) {
        const members = path.slice(path.indexOf(current)).sort()
        parentOf.set(members[0], null)
        issues.push({ kind: 'cycle', node_keys: members, detail: `cycle broken at ${members[0]}` })
        break
      }
      onPath.add(current)
      path.push(current)
      current = parentOf.get(current) ?? null
    }
    for (const key of path) resolved.add(key)
  }
  return { parentOf, issues }
}

export function materialize(doc: Y.Doc): Rows {
  const nodes = nodesMap(doc)
  const { parentOf, issues } = resolveTree(doc)

  const childrenOf = new Map<string, Array<{ order: number; node_key: string }>>()
  for (const [key, parent] of parentOf) {
    const bucket = parent ?? ROOT
    if (!childrenOf.has(bucket)) childrenOf.set(bucket, [])
    childrenOf.get(bucket)!.push({ order: nodes.get(key)!.get('order') as number, node_key: key })
  }

  const nodeRows: NodeRow[] = []
  const visit = (parent: string | null, level: number) => {
    const children = childrenOf.get(parent ?? ROOT) ?? []
    children.sort(compareSiblings)
    for (const child of children) {
      nodeRows.push({
        node_key: child.node_key,
        parent_key: parent,
        level,
        order: child.order,
        deleted: nodes.get(child.node_key)!.get('deleted') as boolean,
      })
      visit(child.node_key, level + 1)
    }
  }
  visit(null, 0)

  const blockRows: BlockRow[] = []
  const dangling: string[] = []
  const blocks = blocksMap(doc)
  for (const key of [...blocks.keys()].sort()) {
    const block = blocks.get(key)!
    const nodeKey = block.get('node_key') as string
    if (!nodes.has(nodeKey)) dangling.push(key)
    const fragment = block.get('content') as Y.XmlFragment
    blockRows.push({
      block_key: key,
      node_key: nodeKey,
      type: block.get('type') as BlockType,
      deleted: block.get('deleted') as boolean,
      content: yXmlFragmentToProseMirrorRootNode(fragment, editorSchema).toJSON() as ProseMirrorJSON,
    })
  }
  blockRows.sort((a, b) => (a.node_key < b.node_key ? -1 : a.node_key > b.node_key ? 1 : a.block_key < b.block_key ? -1 : 1))
  if (dangling.length) issues.push({ kind: 'dangling_block', block_keys: dangling, detail: 'block points at a missing node' })

  return { nodes: nodeRows, blocks: blockRows, issues }
}

/** Writes TipTap JSON into a block's fragment, replacing what is there. */
export function setBlockContent(doc: Y.Doc, blockKey: string, json: ProseMirrorJSON): void {
  const fragment = blockFragment(doc, blockKey)
  doc.transact(() => {
    if (fragment.length) fragment.delete(0, fragment.length)
    prosemirrorJSONToYXmlFragment(editorSchema, json, fragment)
  })
}

export function hydrate(rows: Rows): Y.Doc {
  const doc = new Y.Doc()
  doc.transact(() => {
    // Rows are in tree order, so every parent precedes its children.
    for (const node of rows.nodes) {
      createNode(doc, node.node_key, { parent: node.parent_key, order: node.order })
      if (node.deleted) softDeleteNode(doc, node.node_key)
    }
    for (const block of rows.blocks) {
      createBlock(doc, block.block_key, { node_key: block.node_key, type: block.type })
      setBlockContent(doc, block.block_key, block.content)
      if (block.deleted) softDeleteBlock(doc, block.block_key)
    }
  })
  return doc
}
