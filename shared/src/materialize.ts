import { prosemirrorJSONToYXmlFragment, yXmlFragmentToProseMirrorRootNode } from '@tiptap/y-tiptap'
import * as Y from 'yjs'

import { editorSchema } from './editor'
import {
  type BlockMap,
  type BlockType,
  blocksOf,
  type LinkKind,
  type LinkMap,
  linksOf,
  type NodeMap,
  nodesOf,
  readBlock,
  readLink,
  readNode,
} from './schema'

/**
 * Conversion between the live document and the rows Django stores per version.
 * materialize() never mutates the document and is deterministic: replicas with
 * the same Yjs state produce identical rows, including after repairs.
 */

export type ProseMirrorJSON = Record<string, unknown>

export interface NodeRow {
  node_key: string
  parent_key: string | null
  level: number
  order: number
  title: string
  deleted: boolean
}

export interface BlockRow {
  block_key: string
  node_key: string
  type: BlockType
  order: number
  deleted: boolean
  content: ProseMirrorJSON
}

export interface LinkRow {
  link_key: string
  kind: LinkKind
  source_key: string
  target_key: string | null
  competency_key: string | null
}

export type Issue =
  | { kind: 'orphan'; keys: string[] }
  | { kind: 'cycle'; keys: string[] }
  | { kind: 'dangling_block'; keys: string[] }
  | { kind: 'dangling_link'; keys: string[] }

export interface Rows {
  nodes: NodeRow[]
  blocks: BlockRow[]
  links: LinkRow[]
  issues: Issue[]
}

const ROOT = '\u0000root'
const byKey = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)
const byOrderThenKey = (a: { order: number; key: string }, b: { order: number; key: string }) =>
  a.order !== b.order ? a.order - b.order : byKey(a.key, b.key)

/** Parent links with orphans and cycles repaired: the smallest key of a cycle goes back to the root (D4). */
function resolveParents(nodes: Y.Map<NodeMap>): { parentOf: Map<string, string | null>; issues: Issue[] } {
  const parentOf = new Map<string, string | null>()
  const issues: Issue[] = []
  const orphans: string[] = []
  nodes.forEach((node, key) => {
    const parent = readNode(node).parent
    if (parent !== null && !nodes.has(parent)) {
      orphans.push(key)
      parentOf.set(key, null)
    } else {
      parentOf.set(key, parent)
    }
  })
  if (orphans.length) issues.push({ kind: 'orphan', keys: orphans.sort(byKey) })

  const resolved = new Set<string>()
  for (const start of [...parentOf.keys()].sort(byKey)) {
    const path: string[] = []
    const onPath = new Set<string>()
    let current: string | null = start
    while (current !== null && !resolved.has(current)) {
      if (onPath.has(current)) {
        const members = path.slice(path.indexOf(current)).sort(byKey)
        parentOf.set(members[0], null)
        issues.push({ kind: 'cycle', keys: members })
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

export function contentOf(fragment: Y.XmlFragment): ProseMirrorJSON {
  return yXmlFragmentToProseMirrorRootNode(fragment, editorSchema).toJSON() as ProseMirrorJSON
}

/** Raised when the document holds content the editor schema cannot represent (D32: the save fails). */
export class UnrepresentableContent extends Error {}

/**
 * The document as rows. It never changes the document: the conversion runs on a copy, because the
 * underlying converter silently deletes elements and marks the schema does not know; if it had to,
 * the document cannot be represented and the save fails instead (review finding).
 */
export function materialize(doc: Y.Doc): Rows {
  const copy = new Y.Doc()
  Y.applyUpdate(copy, Y.encodeStateAsUpdate(doc))
  let changed = false
  copy.on('update', () => {
    changed = true
  })
  const rows = rowsOf(copy)
  if (changed) throw new UnrepresentableContent('the document holds content the editor schema cannot represent')
  return rows
}

function rowsOf(doc: Y.Doc): Rows {
  const nodes = nodesOf(doc)
  const { parentOf, issues } = resolveParents(nodes)

  const children = new Map<string, Array<{ order: number; key: string }>>()
  for (const [key, parent] of parentOf) {
    const bucket = parent ?? ROOT
    if (!children.has(bucket)) children.set(bucket, [])
    children.get(bucket)!.push({ order: readNode(nodes.get(key)!).order, key })
  }

  const nodeRows: NodeRow[] = []
  const visit = (parent: string | null, level: number) => {
    for (const child of (children.get(parent ?? ROOT) ?? []).sort(byOrderThenKey)) {
      const fields = readNode(nodes.get(child.key)!)
      nodeRows.push({ node_key: child.key, parent_key: parent, level, order: fields.order, title: fields.title, deleted: fields.deleted })
      visit(child.key, level + 1)
    }
  }
  visit(null, 0)

  const blocks = blocksOf(doc)
  const blockRows: BlockRow[] = []
  const dangling: string[] = []
  for (const key of [...blocks.keys()].sort(byKey)) {
    const block = blocks.get(key) as BlockMap
    const fields = readBlock(block)
    if (!nodes.has(fields.node_key)) {
      dangling.push(key)
      continue
    }
    blockRows.push({ block_key: key, ...fields, content: contentOf(block.get('content') as Y.XmlFragment) })
  }
  blockRows.sort((a, b) => byKey(a.node_key, b.node_key) || a.order - b.order || byKey(a.block_key, b.block_key))
  if (dangling.length) issues.push({ kind: 'dangling_block', keys: dangling })

  const present = new Set(blockRows.map((b) => b.block_key))
  const links = linksOf(doc)
  const linkRows: LinkRow[] = []
  const danglingLinks: string[] = []
  for (const key of [...links.keys()].sort(byKey)) {
    const fields = readLink(links.get(key) as LinkMap)
    if (!present.has(fields.source_key) || (fields.target_key !== null && !present.has(fields.target_key))) {
      danglingLinks.push(key)
      continue
    }
    linkRows.push({ link_key: key, ...fields })
  }
  if (danglingLinks.length) issues.push({ kind: 'dangling_link', keys: danglingLinks })

  return { nodes: nodeRows, blocks: blockRows, links: linkRows, issues }
}

export function setBlockContent(doc: Y.Doc, blockKey: string, json: ProseMirrorJSON): void {
  const fragment = blocksOf(doc).get(blockKey)?.get('content') as Y.XmlFragment
  doc.transact(() => {
    if (fragment.length) fragment.delete(0, fragment.length)
    prosemirrorJSONToYXmlFragment(editorSchema, json, fragment)
  })
}

/**
 * A client id that depends only on the rows. Building the same rows twice with it gives the same Yjs
 * items, so documents rebuilt from rows on two loads, or on the server and a reconnecting client,
 * merge instead of conflicting, and comment anchors keep pointing at real items (review finding).
 */
export function stableClientId(rows: Pick<Rows, 'nodes' | 'blocks' | 'links'>): number {
  const text = canonical({ nodes: rows.nodes, blocks: rows.blocks, links: rows.links })
  let hash = 0x811c9dc5
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return hash || 1
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (value && typeof value === 'object') {
    const entries = Object.keys(value as Record<string, unknown>)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`)
    return `{${entries.join(',')}}`
  }
  return JSON.stringify(value) ?? 'null'
}

/** Rebuilds a document from rows deterministically (see stableClientId) into ``doc``. */
export function hydrateStable(rows: Pick<Rows, 'nodes' | 'blocks' | 'links'>, doc: Y.Doc = new Y.Doc()): Y.Doc {
  const built = new Y.Doc()
  built.clientID = stableClientId(rows)
  hydrate(rows, built)
  Y.applyUpdate(doc, Y.encodeStateAsUpdate(built))
  return doc
}

/** Rebuilds a document from rows (when a version has rows but no stored Yjs state). */
export function hydrate(rows: Pick<Rows, 'nodes' | 'blocks' | 'links'>, doc: Y.Doc = new Y.Doc()): Y.Doc {
  doc.transact(() => {
    const nodes = nodesOf(doc)
    for (const row of rows.nodes) {
      const node: NodeMap = new Y.Map()
      node.set('parent', row.parent_key)
      node.set('order', row.order)
      node.set('title', row.title)
      node.set('deleted', row.deleted)
      nodes.set(row.node_key, node)
    }
    const blocks = blocksOf(doc)
    for (const row of rows.blocks) {
      const block: BlockMap = new Y.Map()
      block.set('node_key', row.node_key)
      block.set('type', row.type)
      block.set('order', row.order)
      block.set('deleted', row.deleted)
      const fragment = new Y.XmlFragment()
      block.set('content', fragment)
      blocks.set(row.block_key, block)
      prosemirrorJSONToYXmlFragment(editorSchema, row.content, fragment)
    }
    const links = linksOf(doc)
    for (const row of rows.links) {
      const link: LinkMap = new Y.Map()
      link.set('kind', row.kind)
      link.set('source_key', row.source_key)
      link.set('target_key', row.target_key)
      link.set('competency_key', row.competency_key)
      links.set(row.link_key, link)
    }
  })
  return doc
}
