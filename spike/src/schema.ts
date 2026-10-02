import * as Y from 'yjs'

/**
 * Yjs document schema for one live draft (task 0.2).
 *
 *   doc.getMap('nodes'):  node_key  -> Y.Map { parent, level, order, deleted }
 *   doc.getMap('blocks'): block_key -> Y.Map { node_key, type, deleted, content: Y.XmlFragment }
 *
 * Keys are stable across versions and are chosen by the caller. The stored
 * `level` is a convenience that follows moves locally; the depth computed from
 * `parent` links is authoritative when the document is materialized, because
 * concurrent moves can leave stored levels inconsistent.
 */

export const NODES = 'nodes'
export const BLOCKS = 'blocks'

export const BLOCK_TYPES = ['objective', 'content', 'activity', 'assessment', 'reference'] as const
export type BlockType = (typeof BLOCK_TYPES)[number]

export interface NodeFields {
  parent: string | null
  level: number
  order: number
  deleted: boolean
}

export interface BlockFields {
  node_key: string
  type: BlockType
  deleted: boolean
}

export type NodeMap = Y.Map<string | number | boolean | null>
export type BlockMap = Y.Map<string | boolean | Y.XmlFragment>

export function nodesMap(doc: Y.Doc): Y.Map<NodeMap> {
  return doc.getMap<NodeMap>(NODES)
}

export function blocksMap(doc: Y.Doc): Y.Map<BlockMap> {
  return doc.getMap<BlockMap>(BLOCKS)
}

export function newKey(): string {
  return crypto.randomUUID()
}

function requireNode(doc: Y.Doc, key: string): NodeMap {
  const node = nodesMap(doc).get(key)
  if (!node) throw new Error(`unknown node ${key}`)
  return node
}

function requireBlock(doc: Y.Doc, key: string): BlockMap {
  const block = blocksMap(doc).get(key)
  if (!block) throw new Error(`unknown block ${key}`)
  return block
}

function parentLevel(doc: Y.Doc, parent: string | null): number {
  if (parent === null) return -1
  return requireNode(doc, parent).get('level') as number
}

export function createNode(doc: Y.Doc, key: string, fields: { parent: string | null; order: number }): void {
  if (nodesMap(doc).has(key)) throw new Error(`node ${key} already exists`)
  doc.transact(() => {
    const level = parentLevel(doc, fields.parent) + 1
    const node: NodeMap = new Y.Map()
    node.set('parent', fields.parent)
    node.set('level', level)
    node.set('order', fields.order)
    node.set('deleted', false)
    nodesMap(doc).set(key, node)
  })
}

export function createBlock(doc: Y.Doc, key: string, fields: { node_key: string; type: BlockType }): Y.XmlFragment {
  if (!(BLOCK_TYPES as readonly string[]).includes(fields.type)) throw new Error(`unknown block type ${fields.type}`)
  requireNode(doc, fields.node_key)
  if (blocksMap(doc).has(key)) throw new Error(`block ${key} already exists`)
  const content = new Y.XmlFragment()
  doc.transact(() => {
    const block: BlockMap = new Y.Map()
    block.set('node_key', fields.node_key)
    block.set('type', fields.type)
    block.set('deleted', false)
    block.set('content', content)
    blocksMap(doc).set(key, block)
  })
  return content
}

export function getNode(doc: Y.Doc, key: string): NodeFields {
  const node = requireNode(doc, key)
  return {
    parent: (node.get('parent') as string | null) ?? null,
    level: node.get('level') as number,
    order: node.get('order') as number,
    deleted: node.get('deleted') as boolean,
  }
}

export function getBlock(doc: Y.Doc, key: string): BlockFields {
  const block = requireBlock(doc, key)
  return {
    node_key: block.get('node_key') as string,
    type: block.get('type') as BlockType,
    deleted: block.get('deleted') as boolean,
  }
}

export function blockFragment(doc: Y.Doc, key: string): Y.XmlFragment {
  return requireBlock(doc, key).get('content') as Y.XmlFragment
}

export function listNodes(doc: Y.Doc): Array<NodeFields & { key: string }> {
  return [...nodesMap(doc).keys()].sort().map((key) => ({ key, ...getNode(doc, key) }))
}

export function listBlocks(doc: Y.Doc): Array<BlockFields & { key: string }> {
  return [...blocksMap(doc).keys()].sort().map((key) => ({ key, ...getBlock(doc, key) }))
}

function childrenOf(doc: Y.Doc, parent: string): string[] {
  const out: string[] = []
  nodesMap(doc).forEach((node, key) => {
    if (node.get('parent') === parent) out.push(key)
  })
  return out
}

function setSubtreeLevels(doc: Y.Doc, key: string, level: number): void {
  requireNode(doc, key).set('level', level)
  for (const child of childrenOf(doc, key)) setSubtreeLevels(doc, child, level + 1)
}

export function moveNode(doc: Y.Doc, key: string, target: { parent: string | null; order: number }): void {
  const node = requireNode(doc, key)
  if (target.parent === key) throw new Error('a node cannot be its own parent')
  doc.transact(() => {
    node.set('parent', target.parent)
    node.set('order', target.order)
    setSubtreeLevels(doc, key, parentLevel(doc, target.parent) + 1)
  })
}

export function softDeleteNode(doc: Y.Doc, key: string): void {
  requireNode(doc, key).set('deleted', true)
}

export function softDeleteBlock(doc: Y.Doc, key: string): void {
  requireBlock(doc, key).set('deleted', true)
}
