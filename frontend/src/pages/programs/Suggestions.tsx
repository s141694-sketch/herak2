import { applyOutline, applyRewrite } from '@harak2/shared'
import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type * as Y from 'yjs'

import { http } from '../../api'
import { ErrorMessage } from '../../components/ErrorMessage'
import { useAction } from '../../hooks/useResource'
import type { FrameworkVersionDetail, OutlineResult, RewriteResult, Suggestion } from '../../types'

/** What the suggestion components need from the live page. */
export interface SuggestionContext {
  versionId: number
  doc: Y.Doc
  levelCount: number
  framework: FrameworkVersionDetail | undefined
  /** Runs a change of the live document, showing a rule's refusal as the page does for any edit. */
  edit: (change: () => void) => boolean
}

const POLL_MS = 1500

/** Asks for one suggestion and follows it until the agent has answered. */
function useSuggestion(versionId: number) {
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null)
  const action = useAction()

  useEffect(() => {
    if (suggestion?.status !== 'pending') return
    const timer = setTimeout(() => {
      http.get<Suggestion>(`/api/suggestions/${suggestion.id}/`).then(setSuggestion, () => setSuggestion({ ...suggestion }))
    }, POLL_MS)
    return () => clearTimeout(timer)
  }, [suggestion])

  const ask = useCallback(
    async (body: Record<string, unknown>) => {
      const made = await action.run(() => http.post<Suggestion>(`/api/program-versions/${versionId}/suggestions/`, body))
      if (made) setSuggestion(made)
    },
    [action, versionId],
  )
  const decide = async (decision: 'accept' | 'dismiss', reason?: string) => {
    if (!suggestion) return
    const decided = await action.run(() =>
      http.post<Suggestion>(`/api/suggestions/${suggestion.id}/${decision}/`, decision === 'dismiss' ? { reason: reason ?? '' } : undefined),
    )
    if (decided) setSuggestion(decided)
  }
  return { suggestion, action, ask, decide, reset: () => setSuggestion(null) }
}

function Outcome({ suggestion, onClose }: { suggestion: Suggestion; onClose: () => void }) {
  const { t } = useTranslation()
  let message: string
  let tone = 'muted'
  if (suggestion.status === 'pending') message = t('suggestions.pending')
  else if (suggestion.status === 'rejected') message = t('suggestions.rejected')
  else if (suggestion.status === 'accepted') message = t('suggestions.accepted')
  else if (suggestion.status === 'dismissed') message = t('suggestions.dismissed')
  else (message = t(`suggestions.failed.${suggestion.reason}`, { defaultValue: t('suggestions.failed.default') })), (tone = 'error')
  return (
    <p className={tone} data-testid="suggestion-outcome" data-status={suggestion.status}>
      {message}{' '}
      {suggestion.status !== 'pending' && (
        <button type="button" className="link-button" onClick={onClose}>
          {t('suggestions.close')}
        </button>
      )}
    </p>
  )
}

/** Accept, or reject with an optional reason; both are recorded to measure the agent in use (spec 5.5). */
function Decision({ busy, onAccept, onDismiss }: { busy: boolean; onAccept: () => void; onDismiss: (reason: string) => void }) {
  const { t } = useTranslation()
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  if (rejecting) {
    return (
      <form
        className="row"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          onDismiss(reason)
        }}
      >
        <input
          aria-label={t('suggestions.dismissReason')}
          placeholder={t('suggestions.dismissReason')}
          value={reason}
          maxLength={1000}
          data-testid="suggestion-dismiss-reason"
          onChange={(e) => setReason(e.target.value)}
        />
        <button type="submit" className="secondary" disabled={busy} data-testid="suggestion-dismiss-confirm">
          {t('suggestions.dismiss')}
        </button>
      </form>
    )
  }
  return (
    <div className="row">
      <button type="button" className="primary-inline" disabled={busy} data-testid="suggestion-accept" onClick={onAccept}>
        {t('suggestions.accept')}
      </button>
      <button type="button" className="secondary" disabled={busy} data-testid="suggestion-dismiss" onClick={() => setRejecting(true)}>
        {t('suggestions.dismiss')}
      </button>
    </div>
  )
}

function AiNote({ result }: { result: { confidence: string; explanation: string } }) {
  const { t } = useTranslation()
  return (
    <>
      <p className="muted">
        <span className="badge badge-ai">{t('suggestions.aiLabel')}</span> {t(`suggestions.confidence.${result.confidence}`)}
      </p>
      {result.explanation && <p className="muted">{result.explanation}</p>}
    </>
  )
}

/** A better wording for a weak objective, written into the block when the author accepts it. */
export function RewriteSuggestion({ blockKey, ctx }: { blockKey: string; ctx: SuggestionContext }) {
  const { t } = useTranslation()
  const { suggestion, action, ask, decide, reset } = useSuggestion(ctx.versionId)
  const [note, setNote] = useState<string | null>(null)

  if (!suggestion) {
    return (
      <div className="suggestion">
        <button type="button" className="link-button" data-testid="suggest-rewrite" disabled={action.busy} onClick={() => void ask({ kind: 'rewrite', block_key: blockKey })}>
          {t('suggestions.rewrite')}
        </button>
        <ErrorMessage code={action.error} testId="suggestion-error" />
      </div>
    )
  }
  const result = suggestion.status === 'ready' ? (suggestion.result as RewriteResult) : null
  return (
    <div className="suggestion panel" data-testid="rewrite-suggestion">
      {result ? (
        <>
          <AiNote result={result} />
          <p>
            {t('suggestions.original')}: <span data-testid="suggestion-original">{suggestion.original}</span>
          </p>
          <p>
            {t('suggestions.suggested')}: <strong data-testid="suggestion-text">{result.objective}</strong>
          </p>
          {note && <p className="error">{note}</p>}
          <Decision
            busy={action.busy}
            onAccept={() => {
              const outcome: { value: ReturnType<typeof applyRewrite> } = { value: 'missing' }
              const done = ctx.edit(() => {
                outcome.value = applyRewrite(ctx.doc, blockKey, suggestion.original ?? '', result.objective)
              })
              if (!done) return
              if (outcome.value !== 'applied') setNote(t('suggestions.changed'))
              else void decide('accept')
            }}
            onDismiss={(reason) => void decide('dismiss', reason)}
          />
        </>
      ) : (
        <Outcome suggestion={suggestion} onClose={reset} />
      )}
      <ErrorMessage code={action.error} testId="suggestion-error" />
    </div>
  )
}

function OutlinePreview({ outline, ctx }: { outline: OutlineResult; ctx: SuggestionContext }) {
  const { t } = useTranslation()
  const competency = (key: string) => ctx.framework?.competencies.find((c) => c.competency_key === key)
  const render = (parent: string) => (
    <ul className="plain outline">
      {outline.nodes
        .filter((node) => node.parent === parent)
        .map((node) => (
          <li key={node.ref} data-testid="outline-node">
            <strong>{node.title}</strong>
            {outline.objectives
              .filter((objective) => objective.node === node.ref)
              .map((objective) => (
                <p key={objective.text} className="outline-objective" data-testid="outline-objective">
                  {objective.text} <span className="chip">{competency(objective.competency_key)?.code ?? objective.competency}</span>
                </p>
              ))}
            {render(node.ref)}
          </li>
        ))}
    </ul>
  )
  return (
    <>
      <h3>{t('suggestions.outlinePreview')}</h3>
      {render('')}
      {(outline.dropped.nodes > 0 || outline.dropped.objectives > 0) && (
        <p className="muted">{t('suggestions.dropped', { nodes: outline.dropped.nodes, objectives: outline.dropped.objectives })}</p>
      )}
    </>
  )
}

/** A first outline from the competencies the version targets, added to the document when the author accepts it. */
export function OutlineSuggestion({ ctx }: { ctx: SuggestionContext }) {
  const { t } = useTranslation()
  const { suggestion, action, ask, decide, reset } = useSuggestion(ctx.versionId)

  if (!suggestion) {
    return (
      <div className="suggestion">
        <button type="button" className="secondary" data-testid="suggest-outline" disabled={action.busy} onClick={() => void ask({ kind: 'outline' })}>
          {t('suggestions.outline')}
        </button>
        <ErrorMessage code={action.error} testId="suggestion-error" />
      </div>
    )
  }
  const result = suggestion.status === 'ready' ? (suggestion.result as OutlineResult) : null
  return (
    <section className="suggestion panel" data-testid="outline-suggestion">
      {result ? (
        <>
          <AiNote result={result} />
          <OutlinePreview outline={result} ctx={ctx} />
          <Decision
            busy={action.busy}
            onAccept={() => {
              if (ctx.edit(() => applyOutline(ctx.doc, result, ctx.levelCount))) void decide('accept')
            }}
            onDismiss={(reason) => void decide('dismiss', reason)}
          />
        </>
      ) : (
        <Outcome suggestion={suggestion} onClose={reset} />
      )}
      <ErrorMessage code={action.error} testId="suggestion-error" />
    </section>
  )
}
