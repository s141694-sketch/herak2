import type { Editor } from '@tiptap/core'
import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type * as Y from 'yjs'

import { http } from '../../api'
import { ErrorMessage } from '../../components/ErrorMessage'
import { useAction } from '../../hooks/useResource'
import { anchorFromSelection, type Resolved, resolveInEditor } from '../../live/commentAnchors'
import type { ProgramComment } from '../../types'

export interface CommentContext {
  programId: number
  versionId: number
  comments: ProgramComment[]
  reload: () => void
  canResolve: boolean
  canReopen: boolean
  editorFor: (blockKey: string) => Editor | undefined
  fragmentFor: (blockKey: string) => Y.XmlFragment | undefined
  doc: Y.Doc
  liveBlocks: Set<string>
}

export type Placement = Resolved['status'] | 'block'

/** The server's limit on a comment or a reply (the comments serializers). */
const REPLY_MAX_LENGTH = 5000

/** Where a comment sits now in the live document. */
export function placementOf(comment: ProgramComment, ctx: CommentContext): { placement: Placement; resolved?: Resolved } {
  if (!comment.block_key) return { placement: 'block' }
  if (!ctx.liveBlocks.has(comment.block_key)) return { placement: 'orphaned' }
  if (!comment.anchor) return { placement: 'block' }
  const editor = ctx.editorFor(comment.block_key)
  const fragment = ctx.fragmentFor(comment.block_key)
  if (!editor || !fragment) return { placement: 'block' }
  const resolved = resolveInEditor(editor, fragment, ctx.doc, comment.anchor, comment.quoted)
  return { placement: resolved.status, resolved }
}

export function CommentCard({ comment, ctx, placement, resolved }: { comment: ProgramComment; ctx: CommentContext; placement: Placement; resolved?: Resolved }) {
  const { t } = useTranslation()
  const action = useAction()
  const [reply, setReply] = useState('')
  const editor = comment.block_key ? ctx.editorFor(comment.block_key) : undefined

  const run = (fn: () => Promise<unknown>) => void action.run(fn).then((done) => done !== undefined && ctx.reload())

  return (
    <article
      className={`comment comment-${comment.category} comment-${comment.status}`}
      data-testid="comment"
      data-placement={placement}
      data-status={comment.status}
    >
      <header className="row">
        <span className={`badge badge-${comment.category}`}>{t(`commentCategory.${comment.category}`)}</span>
        <span className="badge">{t(`commentStatus.${comment.status}`)}</span>
        <span className="muted" data-testid="comment-placement">
          {t(`comments.status_${placement}`)}
        </span>
        {comment.version !== ctx.versionId && <span className="muted">{t('comments.fromVersion', { number: comment.version_number })}</span>}
      </header>
      {comment.quoted && (
        <button
          type="button"
          className="link-button quote"
          disabled={!editor || resolved?.from === undefined}
          onClick={() => {
            if (editor && resolved?.from !== undefined && resolved.to !== undefined) {
              editor.chain().focus().setTextSelection({ from: resolved.from, to: resolved.to }).scrollIntoView().run()
            }
          }}
        >
          {t('comments.quoted', { text: comment.quoted })}
        </button>
      )}
      {placement === 'changed' && resolved?.current && <p className="muted">{t('comments.now', { text: resolved.current })}</p>}
      <p className="comment-body">{comment.body}</p>
      <p className="muted">{comment.author.full_name || comment.author.email}</p>
      {comment.replies.map((r) => (
        <p key={r.id} className="reply">
          <strong>{r.author.full_name || r.author.email}:</strong> {r.body}
        </p>
      ))}
      <ErrorMessage code={action.error} />
      <form
        className="row"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          run(async () => {
            await http.post(`/api/comments/${comment.id}/replies/`, { body: reply })
            setReply('')
            return true
          })
        }}
      >
        <input
          aria-label={t('comments.reply')}
          placeholder={t('comments.replyPlaceholder')}
          value={reply}
          required
          maxLength={REPLY_MAX_LENGTH}
          onChange={(e) => setReply(e.target.value)}
        />
        <button type="submit" className="secondary">
          {t('comments.reply')}
        </button>
        {comment.status === 'open' && ctx.canResolve && (
          <button type="button" className="secondary" data-testid="comment-resolve" onClick={() => run(() => http.post(`/api/comments/${comment.id}/resolve/`))}>
            {t('comments.resolve')}
          </button>
        )}
        {comment.status === 'resolved' && ctx.canReopen && (
          <button type="button" className="secondary" data-testid="comment-reopen" onClick={() => run(() => http.post(`/api/comments/${comment.id}/reopen/`))}>
            {t('comments.reopen')}
          </button>
        )}
      </form>
    </article>
  )
}

/** Comment on the current selection of a block, or on the whole block when nothing is selected. */
export function NewComment({ blockKey, ctx }: { blockKey: string; ctx: CommentContext }) {
  const { t } = useTranslation()
  const action = useAction()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<{ anchor: { start: string; end: string } | null; quoted: string }>({ anchor: null, quoted: '' })
  const [body, setBody] = useState('')
  const [category, setCategory] = useState<'must_fix' | 'suggestion'>('suggestion')

  function start() {
    const editor = ctx.editorFor(blockKey)
    const fragment = ctx.fragmentFor(blockKey)
    const fromSelection = editor && fragment ? anchorFromSelection(editor, fragment, ctx.doc) : null
    setDraft(fromSelection ?? { anchor: null, quoted: '' })
    setOpen(true)
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    const done = await action.run(() =>
      http.post(`/api/programs/${ctx.programId}/comments/`, {
        version: ctx.versionId,
        block_key: blockKey,
        anchor: draft.anchor,
        quoted: draft.quoted,
        body,
        category,
      }),
    )
    if (done) {
      setOpen(false)
      setBody('')
      ctx.reload()
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        className="link-button"
        data-testid="comment-selection"
        // Keep the editor's selection: the button must not take focus before it is read.
        onMouseDown={(event) => event.preventDefault()}
        onClick={start}
      >
        {t('comments.add')}
      </button>
    )
  }
  return (
    <form className="new-comment" onSubmit={save} data-testid="new-comment">
      {draft.quoted ? <p className="quote">{t('comments.quoted', { text: draft.quoted })}</p> : <p className="muted">{t('comments.addBlock')}</p>}
      <label className="field">
        <span>{t('comments.category')}</span>
        <select value={category} data-testid="comment-category" onChange={(e) => setCategory(e.target.value as 'must_fix' | 'suggestion')}>
          <option value="suggestion">{t('commentCategory.suggestion')}</option>
          <option value="must_fix">{t('commentCategory.must_fix')}</option>
        </select>
      </label>
      <label className="field">
        <span>{t('comments.body')}</span>
        <textarea required value={body} maxLength={REPLY_MAX_LENGTH} data-testid="comment-body" onChange={(e) => setBody(e.target.value)} />
      </label>
      <ErrorMessage code={action.error} />
      <div className="row">
        <button type="submit" className="primary-inline" data-testid="comment-save" disabled={action.busy}>
          {t('comments.save')}
        </button>
        <button type="button" className="secondary" onClick={() => setOpen(false)}>
          {t('common.cancel')}
        </button>
      </div>
    </form>
  )
}
