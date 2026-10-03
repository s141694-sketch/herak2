import { blockFragment, editorExtensions } from '@harak2/shared'
import Collaboration from '@tiptap/extension-collaboration'
import { EditorContent, useEditor } from '@tiptap/react'
import { useEffect } from 'react'
import type * as Y from 'yjs'

import { BidiDirection } from '../editor/bidi'

/** One block's rich text, bound to the block's XmlFragment in the live document. */
export function LiveBlockEditor({ doc, blockKey, editable }: { doc: Y.Doc; blockKey: string; editable: boolean }) {
  const editor = useEditor(
    {
      extensions: [...editorExtensions(), BidiDirection, Collaboration.configure({ fragment: blockFragment(doc, blockKey) })],
      editable,
      editorProps: { attributes: { class: 'block-editor', 'data-testid': 'block-editor' } },
    },
    [doc, blockKey],
  )

  useEffect(() => {
    editor?.setEditable(editable)
  }, [editor, editable])

  return <EditorContent editor={editor} />
}
