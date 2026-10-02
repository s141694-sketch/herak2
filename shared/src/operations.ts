import * as Y from 'yjs'

import {
  type BlockMap,
  type BlockType,
  BLOCK_TYPES,
  blocksOf,
  type LinkKind,
  type LinkMap,
  linksOf,
  newKey,
  type NodeMap,
  nodesOf,
  readNode,
} from './schema'

/**
 * Edits a client makes to the live document. Each one is a single Yjs
 * transaction. Local guards mirror the server's rules; concurrent edits can
 * still break them, which materialize() repairs or reports.
 */

export class DocumentRuleError extends Error {
  constructor(public readonly code: string) {
    super(code)
  }
}

export function depthOf(doc: Y.Doc, key: string): number {
  const nodes = nodesOf(doc)
  let depth = 0
  const seen = new Set<string>()
  let parent = (nodes.get(key)?.get('parent') as string | null) ?? null
  while (parent !== null && !seen.has(parent)) {
    seen.add(parent)
    depth += 1
    parent = (nodes.get(parent)?.get('parent') as string | null) ?? null
  }
  return depth
}

function subtreeHeight(doc: Y.Doc, key: string, seen = new Set<string>()): number {
  if (seen.has(key)) return 0
  seen.add(key)
  let height = 0
  nodesOf(doc).forEach((node, childKey) => {
    if (node.get('parent') === key) height = Math.max(height, 1 + subtreeHeight(doc, childKey, seen))
  })
  return height
}

function nextOrder(entries: Iterable<{ order: number }>): number {
  let max = 0
  for (const entry of entries) max = Math.max(max, entry.order)
  return max + 1
}

function siblings(doc: Y.Doc, parent: string | null) {
  const found: Array<{ key: string; order: number }> = []
  nodesOf(doc).forEach((node, key) => {
    if (((node.get('parent') as string | null) ?? null) === parent) found.push({ key, order: (node.get('order') as number) ?? 0 })
  })
  return found
}

export function addNode(
  doc: Y.Doc,
  fields: { parent: string | null; title: string; order?: number; key?: string },
  levelCount: number,
): string {
  const nodes = nodesOf(doc)
  if (fields.parent !== null && !nodes.has(fields.parent)) throw new DocumentRuleError('node_parent_invalid')
  const depth = fields.parent === null ? 0 : depthOf(doc, fields.parent) + 1
  if (depth >= levelCount) throw new DocumentRuleError('node_level_exceeds_template')
  const key = fields.key ?? newKey()
  doc.transact(() => {
    const node: NodeMap = new Y.Map()
    node.set('parent', fields.parent)
    node.set('order', fields.order ?? nextOrder(siblings(doc, fields.parent)))
    node.set('title', fields.title.trim())
    node.set('deleted', false)
    nodes.set(key, node)
  })
  return key
}

export function renameNode(doc: Y.Doc, key: string, title: string): void {
  const node = nodesOf(doc).get(key)
  if (!node) throw new DocumentRuleError('node_parent_invalid')
  node.set('title', title.trim())
}

export function isSelfOrDescendant(doc: Y.Doc, key: string, candidate: string | null): boolean {
  const nodes = nodesOf(doc)
  const seen = new Set<string>()
  let current = candidate
  while (current !== null && !seen.has(current)) {
    if (current === key) return true
    seen.add(current)
    current = (nodes.get(current)?.get('parent') as string | null) ?? null
  }
  return false
}

export function moveNode(doc: Y.Doc, key: string, target: { parent: string | null; order?: number }, levelCount: number): void {
  const nodes = nodesOf(doc)
  const node = nodes.get(key)
  if (!node) throw new DocumentRuleError('node_parent_invalid')
  if (target.parent !== null && !nodes.has(target.parent)) throw new DocumentRuleError('node_parent_invalid')
  if (isSelfOrDescendant(doc, key, target.parent)) throw new DocumentRuleError('node_move_cycle')
  const depth = target.parent === null ? 0 : depthOf(doc, target.parent) + 1
  if (depth + subtreeHeight(doc, key) >= levelCount) throw new DocumentRuleError('node_level_exceeds_template')
  doc.transact(() => {
    node.set('parent', target.parent)
    node.set('order', target.order ?? nextOrder(siblings(doc, target.parent).filter((s) => s.key !== key)))
  })
}

export function setNodeDeleted(doc: Y.Doc, key: string, deleted: boolean): void {
  const node = nodesOf(doc).get(key)
  if (!node) throw new DocumentRuleError('node_parent_invalid')
  node.set('deleted', deleted)
}

export function addBlock(doc: Y.Doc, fields: { node_key: string; type: BlockType; order?: number; key?: string }): string {
  if (!(BLOCK_TYPES as readonly string[]).includes(fields.type)) throw new DocumentRuleError('block_type_invalid')
  if (!nodesOf(doc).has(fields.node_key)) throw new DocumentRuleError('block_node_invalid')
  const blocks = blocksOf(doc)
  const key = fields.key ?? newKey()
  const existing: Array<{ order: number }> = []
  blocks.forEach((block) => {
    if (block.get('node_key') === fields.node_key) existing.push({ order: (block.get('order') as number) ?? 0 })
  })
  doc.transact(() => {
    const block: BlockMap = new Y.Map()
    block.set('node_key', fields.node_key)
    block.set('type', fields.type)
    block.set('order', fields.order ?? nextOrder(existing))
    block.set('deleted', false)
    block.set('content', new Y.XmlFragment())
    blocks.set(key, block)
  })
  return key
}

export function setBlockDeleted(doc: Y.Doc, key: string, deleted: boolean): void {
  const block = blocksOf(doc).get(key)
  if (!block) throw new DocumentRuleError('block_node_invalid')
  block.set('deleted', deleted)
}

export function addLink(
  doc: Y.Doc,
  fields: { kind: LinkKind; source_key: string; target_key?: string | null; competency_key?: string | null },
): string {
  const blocks = blocksOf(doc)
  if (!blocks.has(fields.source_key)) throw new DocumentRuleError('link_invalid')
  if (fields.target_key && !blocks.has(fields.target_key)) throw new DocumentRuleError('link_invalid')
  const duplicate = [...linksOf(doc).values()].some(
    (link) =>
      link.get('kind') === fields.kind &&
      link.get('source_key') === fields.source_key &&
      (link.get('target_key') ?? null) === (fields.target_key ?? null) &&
      (link.get('competency_key') ?? null) === (fields.competency_key ?? null),
  )
  if (duplicate) throw new DocumentRuleError('link_exists')
  const key = newKey()
  doc.transact(() => {
    const link: LinkMap = new Y.Map()
    link.set('kind', fields.kind)
    link.set('source_key', fields.source_key)
    link.set('target_key', fields.target_key ?? null)
    link.set('competency_key', fields.competency_key ?? null)
    linksOf(doc).set(key, link)
  })
  return key
}

export function removeLink(doc: Y.Doc, key: string): void {
  linksOf(doc).delete(key)
}

export { readNode }
