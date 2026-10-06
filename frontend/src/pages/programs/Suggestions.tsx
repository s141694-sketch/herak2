import { applyImport, applyOutline, applyRewrite, checkImport, checkOutline, rewriteState } from '@harak2/shared'
import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type * as Y from 'yjs'

import { http } from '../../api'
import { ErrorMessage } from '../../components/ErrorMessage'
import { useAction } from '../../hooks/useResource'
import type { FrameworkVersionDetail, ImportResult, OutlineResult, RewriteResult, Suggestion } from '../../types'

/** What the suggestion components need from the live page. */
export interface SuggestionContext {
  versionId: number
  doc: Y.Doc
  levelCount: number
  framework: FrameworkVersionDetail | undefined
  /** Whether the document can be written now (connected, synced, a draft); asking and accepting wait for it. */
  editable: boolean
  /** Runs a change of the live document, showing a rule's refusal as the page does for any edit. */
  edit: (change: () => void) => boolean
  /** The author's open suggestion of this kind and subject when the page was opened, to pick up where they were. */
  restore: (kind: Suggestion['kind'], subject: string) => Suggestion | undefined
}

const OPEN = new Set(['pending', 'ready'])

/** The open suggestions the signed-in author asked for on this version, read once when the page opens. */
export function useOpenSuggestions(versionId: number, userId: number | undefined) {
  const [open, setOpen] = useState<Suggestion[]>([])
  useEffect(() => {
    if (userId === undefined) return
    let current = true
    http.get<Suggestion[]>(`/api/program-versions/${versionId}/suggestions/`).then(
      (all) => current && setOpen(all.filter((s) => OPEN.has(s.status) && s.requested_by?.id === userId)),
      () => undefined,
    )
    return () => {
      current = false
    }
  }, [versionId, userId])
  return useCallback((kind: Suggestion['kind'], subject: string) => open.find((s) => s.kind === kind && s.subject === subject), [open])
}

/** Polls start quickly and slow down: an answer usually comes in seconds, a slow one should not cost a request a second. */
const POLL_MS = 1500
const POLL_MAX_MS = 15_000

/** Asks for one suggestion and follows it until the agent has answered. */
function useSuggestion(ctx: SuggestionContext, kind: Suggestion['kind'], subject: string) {
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null)
  const action = useAction()
  const polls = useRef(0)
  // An open suggestion from before a reload is picked up once; after that only the author's requests count.
  const restored = useRef(false)
  const found = restored.current || suggestion ? undefined : ctx.restore(kind, subject)
  useEffect(() => {
    if (!found) return
    restored.current = true
    setSuggestion(found)
  }, [found])

  useEffect(() => {
    if (suggestion?.status !== 'pending') {
      polls.current = 0
      return
    }
    const delay = Math.min(POLL_MS * 2 ** Math.floor(polls.current / 4), POLL_MAX_MS)
    const timer = setTimeout(() => {
      polls.current += 1
      http.get<Suggestion>(`/api/suggestions/${suggestion.id}/`).then(setSuggestion, () => setSuggestion({ ...suggestion }))
    }, delay)
    return () => clearTimeout(timer)
  }, [suggestion])

  const ask = useCallback(
    async (body: Record<string, unknown>) => {
      restored.current = true
      const made = await action.run(() => http.post<Suggestion>(`/api/program-versions/${ctx.versionId}/suggestions/`, body))
      if (made) setSuggestion(made)
    },
    [action, ctx.versionId],
  )
  const decide = async (decision: 'accept' | 'dismiss', reason?: string): Promise<Suggestion | undefined> => {
    if (!suggestion) return undefined
    const decided = await action.run(() =>
      http.post<Suggestion>(`/api/suggestions/${suggestion.id}/${decision}/`, decision === 'dismiss' ? { reason: reason ?? '' } : undefined),
    )
    if (decided) setSuggestion(decided)
    return decided
  }
  /**
   * Accepting is recorded first, so the server lets only one editor accept a suggestion and it is never written
   * twice; it is checked against the rules on a copy of the document before, and written as the server returned
   * it after. ``check`` throws a rule's refusal; ``write`` returns false when the document changed in between.
   * Returns true when the acceptance was recorded but the document could not take it any more.
   */
  const accept = async (check: () => void, write: (decided: Suggestion) => boolean): Promise<boolean> => {
    if (!ctx.edit(check)) return false
    const decided = await decide('accept')
    if (decided?.status !== 'accepted') return false
    let written = false
    ctx.edit(() => {
      written = write(decided)
    })
    return !written
  }
  return { suggestion, action, ask, decide, accept, reset: () => setSuggestion(null) }
}

function Outcome({ suggestion, onClose, note }: { suggestion: Suggestion; onClose: () => void; note?: string }) {
  const { t } = useTranslation()
  let message: string
  let tone = 'muted'
  if (suggestion.status === 'pending') message = t('suggestions.pending')
  else if (suggestion.status === 'rejected') message = t('suggestions.rejected')
  else if (suggestion.status === 'accepted') message = note ?? t(`suggestions.accepted.${suggestion.kind}`)
  else if (suggestion.status === 'dismissed') message = t('suggestions.dismissed')
  else (message = t(`suggestions.failed.${suggestion.reason}`, { defaultValue: t('suggestions.failed.default') })), (tone = 'error')
  if (note) tone = 'error'
  return (
    <p className={tone} role="status" data-testid="suggestion-outcome" data-status={suggestion.status}>
      {message}{' '}
      <button type="button" className="link-button" data-testid="suggestion-close" onClick={onClose}>
        {suggestion.status === 'pending' ? t('suggestions.hide') : t('suggestions.close')}
      </button>
    </p>
  )
}

/** Accept, or reject with an optional reason; both are recorded to measure the agent in use (spec 5.5). */
function Decision({ busy, editable, onAccept, onDismiss }: { busy: boolean; editable: boolean; onAccept: () => void; onDismiss: (reason: string) => void }) {
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
        <button type="button" className="link-button" data-testid="suggestion-dismiss-cancel" onClick={() => setRejecting(false)}>
          {t('common.cancel')}
        </button>
      </form>
    )
  }
  return (
    <div className="row">
      <button type="button" className="primary-inline" disabled={busy || !editable} data-testid="suggestion-accept" onClick={onAccept}>
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
  const { suggestion, action, ask, decide, accept, reset } = useSuggestion(ctx, 'rewrite', blockKey)
  const [note, setNote] = useState<string | null>(null)
  const close = () => {
    setNote(null)
    reset()
  }

  if (!suggestion) {
    return (
      <div className="suggestion">
        <button
          type="button"
          className="link-button"
          data-testid="suggest-rewrite"
          disabled={action.busy || !ctx.editable}
          onClick={() => void ask({ kind: 'rewrite', block_key: blockKey })}
        >
          {t('suggestions.rewrite')}
        </button>
        <ErrorMessage code={action.error} testId="suggestion-error" />
      </div>
    )
  }
  const result = suggestion.status === 'ready' ? (suggestion.result as RewriteResult) : null
  const original = suggestion.original ?? ''
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
          {note && (
            <p className="error" role="alert">
              {note}
            </p>
          )}
          <Decision
            busy={action.busy}
            editable={ctx.editable}
            onAccept={async () => {
              setNote(null)
              if (rewriteState(ctx.doc, blockKey, original) !== 'applied') {
                setNote(t('suggestions.changed'))
                return
              }
              const lost = await accept(
                () => undefined,
                (decided) => applyRewrite(ctx.doc, blockKey, original, (decided.result as RewriteResult).objective) === 'applied',
              )
              if (lost) setNote(t('suggestions.notWritten'))
            }}
            onDismiss={(reason) => void decide('dismiss', reason)}
          />
        </>
      ) : (
        <Outcome suggestion={suggestion} onClose={close} note={note ?? undefined} />
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
  const { suggestion, action, ask, decide, accept, reset } = useSuggestion(ctx, 'outline', '')
  const [note, setNote] = useState<string | null>(null)

  if (!suggestion) {
    return (
      <div className="suggestion">
        <button type="button" className="secondary" data-testid="suggest-outline" disabled={action.busy || !ctx.editable} onClick={() => void ask({ kind: 'outline' })}>
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
            editable={ctx.editable}
            onAccept={async () => {
              const lost = await accept(
                () => checkOutline(ctx.doc, result, ctx.levelCount),
                (decided) => (applyOutline(ctx.doc, decided.result as OutlineResult, ctx.levelCount), true),
              )
              setNote(lost ? t('suggestions.notWritten') : null)
            }}
            onDismiss={(reason) => void decide('dismiss', reason)}
          />
        </>
      ) : (
        <Outcome
          suggestion={suggestion}
          note={note ?? undefined}
          onClose={() => {
            setNote(null)
            reset()
          }}
        />
      )}
      <ErrorMessage code={action.error} testId="suggestion-error" />
    </section>
  )
}

function ImportPreview({ layout }: { layout: ImportResult }) {
  const { t } = useTranslation()
  const render = (parent: string) => (
    <ul className="plain outline">
      {layout.nodes
        .filter((node) => node.parent === parent)
        .map((node) => (
          <li key={node.ref} data-testid="import-node">
            <strong>{node.title}</strong>
            {layout.blocks
              .filter((block) => block.node === node.ref)
              .map((block, index) => (
                <p key={`${block.node}-${index}`} className="outline-objective" data-testid="import-block" data-type={block.type}>
                  <span className={`badge badge-${block.type}`}>{t(`blockType.${block.type}`)}</span> {block.text}
                </p>
              ))}
            {render(node.ref)}
          </li>
        ))}
    </ul>
  )
  return (
    <>
      <h3>{t('suggestions.importPreview')}</h3>
      {layout.warnings.map((code) => (
        <p key={code} className="muted">
          {t(`suggestions.warnings.${code}`, { defaultValue: code })}
        </p>
      ))}
      {render('')}
      {layout.unplaced.length > 0 && (
        <details data-testid="import-unplaced">
          <summary>{t('suggestions.unplaced', { count: layout.unplaced.length })}</summary>
          <ul className="plain muted">
            {layout.unplaced.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}

/** Curriculum text laid out on the tree: Harak's rules first, the import agent when it may help; nothing reaches
 * the document before the author accepts it. */
interface ReadFile {
  file: { id: number; name: string }
  text: string
  warnings: string[]
}

export function ImportSuggestion({ ctx }: { ctx: SuggestionContext }) {
  const { t } = useTranslation()
  const { suggestion, action, ask, decide, accept, reset } = useSuggestion(ctx, 'import', '')
  const [open, setOpen] = useState(false)
  const [source, setSource] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const reading = useAction()
  const [read, setRead] = useState<ReadFile | null>(null)

  /** Task 7.1: the file is kept and its text put in the box, for the author to check before asking. */
  const readFile = async (file: File) => {
    setRead(null)
    const answer = await reading.run(() => http.upload<ReadFile>(`/api/program-versions/${ctx.versionId}/import-file/`, file))
    if (answer) {
      setRead(answer)
      setSource(answer.text)
    }
  }

  if (!suggestion) {
    if (!open) {
      return (
        <div className="suggestion">
          <button type="button" className="secondary" data-testid="import-open" onClick={() => setOpen(true)}>
            {t('suggestions.import')}
          </button>
        </div>
      )
    }
    return (
      <form
        className="suggestion panel"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          void ask({ kind: 'import', text: source, ...(read ? { source_file: read.file.id } : {}) })
        }}
      >
        <label className="field">
          <span>{t('suggestions.importFile')}</span>
          <input
            type="file"
            accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
            disabled={reading.busy || !ctx.editable}
            data-testid="import-file"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void readFile(file)
            }}
          />
        </label>
        <p className="muted small">{t('suggestions.importFileHint')}</p>
        {reading.busy && (
          <p className="muted" role="status">
            {t('suggestions.importReading')}
          </p>
        )}
        {read && (
          <p className="notice" role="status" data-testid="import-file-read">
            {t('suggestions.importFileRead', { name: read.file.name })}
            {read.warnings.map((code) => (
              <span key={code}> {t(`suggestions.importWarnings.${code}`, { defaultValue: '' })}</span>
            ))}
          </p>
        )}
        {reading.error && (
          <div role="alert" className="error" data-testid="import-file-error">
            <p>{t(`errors.${reading.error}`, { defaultValue: t('errors.unknown') })}</p>
            <p>{t('suggestions.importPasteInstead')}</p>
          </div>
        )}
        <label className="field">
          <span>{t('suggestions.importText')}</span>
          <textarea required rows={10} value={source} maxLength={200_000} data-testid="import-text" onChange={(e) => setSource(e.target.value)} />
        </label>
        <p className="muted">{t('suggestions.importConfirm')}</p>
        <div className="row">
          <button type="submit" className="primary-inline" disabled={action.busy || !ctx.editable} data-testid="import-submit">
            {t('suggestions.importSubmit')}
          </button>
          <button type="button" className="secondary" onClick={() => setOpen(false)}>
            {t('common.cancel')}
          </button>
        </div>
        <ErrorMessage code={action.error} testId="suggestion-error" />
      </form>
    )
  }
  const layout = suggestion.status === 'ready' ? (suggestion.result as ImportResult) : null
  return (
    <section className="suggestion panel" data-testid="import-suggestion" data-source={layout?.source ?? ''}>
      {layout ? (
        <>
          {layout.source === 'ai' ? (
            <AiNote result={{ confidence: layout.confidence ?? 'low', explanation: layout.explanation ?? '' }} />
          ) : (
            <p className="muted" data-testid="import-rules-note">
              <span className="badge">{t('suggestions.importRules')}</span>{' '}
              {t(`suggestions.importFallback.${suggestion.reason}`, { defaultValue: t('suggestions.importFallback.default') })}{' '}
              {t('suggestions.importRulesAccuracy')}
            </p>
          )}
          <ImportPreview layout={layout} />
          <Decision
            busy={action.busy}
            editable={ctx.editable}
            onAccept={async () => {
              const lost = await accept(
                () => checkImport(ctx.doc, layout, ctx.levelCount),
                (decided) => (applyImport(ctx.doc, decided.result as ImportResult, ctx.levelCount), true),
              )
              setNote(lost ? t('suggestions.notWritten') : null)
            }}
            onDismiss={(reason) => void decide('dismiss', reason)}
          />
        </>
      ) : (
        <Outcome
          suggestion={suggestion}
          note={note ?? undefined}
          onClose={() => {
            setNote(null)
            reset()
            setOpen(false)
          }}
        />
      )}
      <ErrorMessage code={action.error} testId="suggestion-error" />
    </section>
  )
}
