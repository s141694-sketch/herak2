import Collaboration from '@tiptap/extension-collaboration'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import type * as Y from 'yjs'

/** One TipTap editor bound to the XmlFragment nested inside a block's Y.Map. */
export function BlockEditor({ blockKey, type, fragment }: { blockKey: string; type: string; fragment: Y.XmlFragment }) {
  const editor = useEditor({
    extensions: [StarterKit.configure({ undoRedo: false }), Collaboration.configure({ fragment })],
    editorProps: { attributes: { dir: 'auto', lang: 'ar', 'data-block': blockKey, 'data-type': type } },
  })
  return (
    <div className="editor" data-testid={`block-${blockKey}`}>
      <div className="block-label">{type}</div>
      <EditorContent editor={editor} />
    </div>
  )
}
