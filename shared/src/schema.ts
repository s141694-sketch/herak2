import * as Y from 'yjs'

/**
 * Layout of the live draft document (phase 0 findings, decisions D3, D29, D30).
 *
 *   nodes:  node_key  -> Y.Map { parent: string | null, order: number, title: string, deleted: boolean }
 *   blocks: block_key -> Y.Map { node_key, type, order, deleted, content: Y.XmlFragment }
 *   links:  link_key  -> Y.Map { kind, source_key, target_key | null, competency_key | null }
 *
 * Depth is never stored: it is computed from parent links when the document is
 * materialized, because concurrent moves would leave stored levels stale.
 */

export const BLOCK_TYPES = ['objective', 'content', 'activity', 'assessment', 'reference'] as const
export type BlockType = (typeof BLOCK_TYPES)[number]

export const LINK_KINDS = ['objective_competency', 'assessment_objective', 'objective_parent'] as const
export type LinkKind = (typeof LINK_KINDS)[number]

export type NodeMap = Y.Map<string | number | boolean | null>
export type BlockMap = Y.Map<string | number | boolean | Y.XmlFragment>
export type LinkMap = Y.Map<string | null>

export const nodesOf = (doc: Y.Doc) => doc.getMap<NodeMap>('nodes')
export const blocksOf = (doc: Y.Doc) => doc.getMap<BlockMap>('blocks')
export const linksOf = (doc: Y.Doc) => doc.getMap<LinkMap>('links')

export interface NodeFields {
  parent: string | null
  order: number
  title: string
  deleted: boolean
}

export interface BlockFields {
  node_key: string
  type: BlockType
  order: number
  deleted: boolean
}

export interface LinkFields {
  kind: LinkKind
  source_key: string
  target_key: string | null
  competency_key: string | null
}

export function readNode(node: NodeMap): NodeFields {
  return {
    parent: (node.get('parent') as string | null) ?? null,
    order: (node.get('order') as number) ?? 0,
    title: (node.get('title') as string) ?? '',
    deleted: Boolean(node.get('deleted')),
  }
}

export function readBlock(block: BlockMap): BlockFields {
  return {
    node_key: block.get('node_key') as string,
    type: block.get('type') as BlockType,
    order: (block.get('order') as number) ?? 0,
    deleted: Boolean(block.get('deleted')),
  }
}

export function readLink(link: LinkMap): LinkFields {
  return {
    kind: link.get('kind') as LinkKind,
    source_key: link.get('source_key') as string,
    target_key: (link.get('target_key') as string | null) ?? null,
    competency_key: (link.get('competency_key') as string | null) ?? null,
  }
}

export function blockFragment(doc: Y.Doc, blockKey: string): Y.XmlFragment {
  const block = blocksOf(doc).get(blockKey)
  if (!block) throw new Error(`unknown block ${blockKey}`)
  return block.get('content') as Y.XmlFragment
}

export function newKey(): string {
  return globalThis.crypto.randomUUID()
}
