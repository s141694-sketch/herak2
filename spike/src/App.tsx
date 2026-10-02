import { HocuspocusProvider } from '@hocuspocus/provider'
import Collaboration from '@tiptap/extension-collaboration'
import CollaborationCaret from '@tiptap/extension-collaboration-caret'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { useEffect, useMemo, useState } from 'react'
import * as Y from 'yjs'

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

  const ydoc = useMemo(() => new Y.Doc(), [])
  const [status, setStatus] = useState('connecting')
  const provider = useMemo(
    () =>
      new HocuspocusProvider({
        url: 'ws://localhost:1234',
        name: docName,
        document: ydoc,
        onStatus: ({ status }) => setStatus(status),
      }),
    [docName, ydoc],
  )

  useEffect(() => () => provider.destroy(), [provider])

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
      <div className="editor">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}
