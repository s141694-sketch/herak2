import { HocuspocusProvider } from '@hocuspocus/provider'
import Collaboration from '@tiptap/extension-collaboration'
import CollaborationCaret from '@tiptap/extension-collaboration-caret'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { useEffect, useMemo, useState } from 'react'
import * as Y from 'yjs'

import { BlockEditor } from './BlockEditor'
import { blockFragment, blocksMap, createBlock, createNode, listBlocks, nodesMap } from './schema'

const COLORS = ['#7e1416', '#1e7a4c', '#2e3470', '#7a5b22', '#a0282c']

function pickColor(name: string): string {
  let hash = 0
  for (const ch of name) hash = (hash * 31 + ch.codePointAt(0)!) >>> 0
  return COLORS[hash % COLORS.length]
}

export function App() {
  const params = new URLSearchParams(window.location.search)
  const docName = params.get('doc') ?? 'spike-default'
  const userName = params.get('user') ?? 'anonymous'
  const blocksMode = params.get('mode') === 'blocks'

  const ydoc = useMemo(() => new Y.Doc(), [])
  const [status, setStatus] = useState('connecting')
  const provider = useMemo(
    () =>
      new HocuspocusProvider({
        url: 'ws://localhost:1234',
        name: docName,
        document: ydoc,
        onStatus: ({ status }) => setStatus(status),
        onSynced: () => {
          // Seed a node with two blocks the first time the document is opened.
          if (blocksMode && nodesMap(ydoc).size === 0) {
            createNode(ydoc, 'course', { parent: null, order: 0 })
            createBlock(ydoc, 'objective-1', { node_key: 'course', type: 'objective' })
            createBlock(ydoc, 'content-1', { node_key: 'course', type: 'content' })
          }
          setBlocks(listBlocks(ydoc).map((b) => b.key))
        },
      }),
    [docName, ydoc],
  )
  const [blocks, setBlocks] = useState<string[]>([])

  useEffect(() => () => provider.destroy(), [provider])
  useEffect(() => {
    const refresh = () => setBlocks(listBlocks(ydoc).map((b) => b.key))
    blocksMap(ydoc).observe(refresh)
    return () => blocksMap(ydoc).unobserve(refresh)
  }, [ydoc])

  const editor = useEditor({
    extensions: [
      // History must be handled by Yjs, so the local undo stack is disabled.
      StarterKit.configure({ undoRedo: false }),
      Collaboration.configure({ document: ydoc }),
      CollaborationCaret.configure({ provider, user: { name: userName, color: pickColor(userName) } }),
    ],
    editorProps: { attributes: { dir: 'auto', lang: 'ar' } },
  })

  useEffect(() => {
    // Exposed for Playwright assertions only.
    ;(window as unknown as { __editor?: unknown }).__editor = editor ?? undefined
  }, [editor])

  return (
    <div>
      <div className="toolbar">
        <span>doc: {docName}</span>
        <span>user: {userName}</span>
        <span data-testid="status">{status}</span>
      </div>
      {blocksMode ? (
        blocks.map((key) => (
          <BlockEditor key={key} blockKey={key} type={blocksMap(ydoc).get(key)!.get('type') as string} fragment={blockFragment(ydoc, key)} />
        ))
      ) : (
        <div className="editor">
          <EditorContent editor={editor} />
        </div>
      )}
    </div>
  )
}
