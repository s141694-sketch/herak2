import { blocksOf, linksOf, nodesOf, readBlock, readLink, readNode } from '@harak2/shared'
import { useEffect, useState } from 'react'
import type * as Y from 'yjs'

/** The structure of the live document without block content, for rendering the tree. */
export interface LiveNode {
  key: string
  parent: string | null
  order: number
  title: string
  deleted: boolean
  level: number
}

export interface LiveBlock {
  key: string
  node_key: string
  type: 'objective' | 'content' | 'activity' | 'assessment' | 'reference'
  order: number
  deleted: boolean
}

export interface LiveLink {
  key: string
  kind: 'objective_competency' | 'assessment_objective' | 'objective_parent'
  source_key: string
  target_key: string | null
  competency_key: string | null
}

export interface Snapshot {
  nodes: LiveNode[]
  blocks: LiveBlock[]
  links: LiveLink[]
}

export function snapshotOf(doc: Y.Doc): Snapshot {
  const nodesMap = nodesOf(doc)
  const parents = new Map<string, string | null>()
  nodesMap.forEach((node, key) => parents.set(key, readNode(node).parent))
  const levelOf = (key: string) => {
    let level = 0
    const seen = new Set<string>([key])
    let parent = parents.get(key) ?? null
    while (parent !== null && parents.has(parent) && !seen.has(parent)) {
      seen.add(parent)
      level += 1
      parent = parents.get(parent) ?? null
    }
    return level
  }
  const nodes: LiveNode[] = []
  nodesMap.forEach((node, key) => nodes.push({ key, ...readNode(node), level: levelOf(key) }))
  const blocks: LiveBlock[] = []
  blocksOf(doc).forEach((block, key) => blocks.push({ key, ...readBlock(block) }))
  const links: LiveLink[] = []
  linksOf(doc).forEach((link, key) => links.push({ key, ...readLink(link) }))
  const byOrder = <T extends { order: number; key: string }>(a: T, b: T) => a.order - b.order || (a.key < b.key ? -1 : 1)
  return { nodes: nodes.sort(byOrder), blocks: blocks.sort(byOrder), links: links.sort((a, b) => (a.key < b.key ? -1 : 1)) }
}

/** Re-renders only when the structure changes, not on every keystroke inside a block. */
export function useSnapshot(doc: Y.Doc | undefined): Snapshot {
  const [snapshot, setSnapshot] = useState<Snapshot>({ nodes: [], blocks: [], links: [] })
  useEffect(() => {
    if (!doc) return
    let last = ''
    const refresh = () => {
      const next = snapshotOf(doc)
      const serialized = JSON.stringify(next)
      if (serialized !== last) {
        last = serialized
        setSnapshot(next)
      }
    }
    refresh()
    doc.on('update', refresh)
    return () => doc.off('update', refresh)
  }, [doc])
  return snapshot
}
