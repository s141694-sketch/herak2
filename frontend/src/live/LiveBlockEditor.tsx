import { blockFragment, editorExtensions } from '@harak2/shared'
import type { HocuspocusProvider } from '@hocuspocus/provider'
import type { Editor } from '@tiptap/core'
import Collaboration from '@tiptap/extension-collaboration'
import CollaborationCaret from '@tiptap/extension-collaboration-caret'
import { EditorContent, useEditor } from '@tiptap/react'
import { useEffect } from 'react'
import type * as Y from 'yjs'

import { BidiDirection } from '../editor/bidi'
import { announceBlock, colorFor } from './presence'

/**
 * One block's rich text, bound to the block's XmlFragment in the live document.
 * Other people's carets show with their names; focusing the editor tells them which block I am in.
 */
export function LiveBlockEditor({
  doc,
  provider,
  blockKey,
  editable,
  me,
  onEditor,
}: {
  doc: Y.Doc
  provider: HocuspocusProvider
  blockKey: string
  editable: boolean
  me: { id: number; name: string }
  onEditor?: (blockKey: string, editor: Editor | null) => void
}) {
  const editor = useEditor(
    {
      extensions: [
        ...editorExtensions(),
        BidiDirection,
        Collaboration.configure({ fragment: blockFragment(doc, blockKey) }),
        CollaborationCaret.configure({ provider, user: { name: me.name, color: colorFor(me.id) } }),
      ],
      editable,
      editorProps: { attributes: { class: 'block-editor', 'data-testid': 'block-editor' } },
      onFocus: () => announceBlock(provider, blockKey),
      onBlur: () => announceBlock(provider, null),
    },
    [doc, provider, blockKey],
  )

  useEffect(() => {
    editor?.setEditable(editable)
  }, [editor, editable])

  useEffect(() => {
    if (!editor || !onEditor) return
    onEditor(blockKey, editor)
    return () => onEditor(blockKey, null)
  }, [editor, blockKey, onEditor])

  return <EditorContent editor={editor} />
}
