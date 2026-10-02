import { type Extensions, getSchema } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'

/**
 * The single definition of the block editor's schema. The web client and the
 * collaboration service both build from it, so content converts identically
 * on both sides. Undo is handled by Yjs, and links are never created
 * automatically (decision D5).
 */
export function editorExtensions(): Extensions {
  return [
    StarterKit.configure({
      undoRedo: false,
      link: { autolink: false, openOnClick: false, linkOnPaste: false },
    }),
  ]
}

export const editorSchema = getSchema(editorExtensions())
