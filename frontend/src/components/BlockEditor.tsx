import { wordLists } from '@harak2/shared'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { BidiDirection } from '../editor/bidi'

type Json = Record<string, unknown>

/**
 * One block's rich text. Saves on blur when the content changed. Phase 3 replaces
 * this with the collaborative editor bound to the live Yjs document.
 */
export function BlockEditor({
  content,
  editable,
  onSave,
  testId,
}: {
  content: Json
  editable: boolean
  onSave: (content: Json) => Promise<boolean>
  testId?: string
}) {
  const { t } = useTranslation()
  const saved = useRef(JSON.stringify(content))
  const [state, setState] = useState<'idle' | 'saving' | 'saved'>('idle')

  const editor = useEditor({
    extensions: [
      // Links are not converted automatically (decision D5).
      StarterKit.configure({ link: { autolink: false, openOnClick: false, linkOnPaste: false } }),
      BidiDirection,
    ],
    content,
    editable,
    // Word's lists pasted in become real lists (D5).
    editorProps: { attributes: { class: 'block-editor', 'data-testid': testId ?? 'block-editor' }, transformPastedHTML: wordLists },
    onBlur: async ({ editor: current }) => {
      const next = current.getJSON() as Json
      const serialized = JSON.stringify(next)
      if (serialized === saved.current) return
      setState('saving')
      const ok = await onSave(next)
      if (ok) saved.current = serialized
      setState(ok ? 'saved' : 'idle')
    },
  })

  return (
    <div className="block-editor-wrap">
      <EditorContent editor={editor} />
      {state !== 'idle' && (
        <span className="muted save-state" data-testid="save-state">
          {state === 'saving' ? t('common.saving') : t('common.saved')}
        </span>
      )}
    </div>
  )
}
