import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { http } from '../../api'
import { ErrorMessage } from '../../components/ErrorMessage'
import { useAction, useResource } from '../../hooks/useResource'
import type { StageDecision, Submission } from '../../types'
import { TaskSummary, useDate } from './TasksPage'

function Decisions({ decisions, testId }: { decisions: StageDecision[]; testId: string }) {
  const { t } = useTranslation()
  const date = useDate()
  if (decisions.length === 0) return null
  return (
    <ul className="plain" data-testid={testId}>
      {decisions.map((d) => (
        <li key={d.id} data-decision={d.decision}>
          <span className={d.decision === 'approve' ? 'badge badge-approved' : 'badge badge-returned'}>{t(`workflow.decision.${d.decision}`)}</span>{' '}
          {t('workflow.decidedBy', { stage: d.stage, name: d.user.full_name || d.user.email, date: date(d.created_at) })}
          {d.note && <p className="muted">{d.note}</p>}
        </li>
      ))}
    </ul>
  )
}

/** Approve, or return with a note; the server refuses what spec 6.2 forbids and says why. */
function DecisionForm({ taskId, onDecided }: { taskId: number; onDecided: () => void }) {
  const { t } = useTranslation()
  const action = useAction()
  const [note, setNote] = useState('')
  const decide = async (decision: 'approve' | 'return', event?: FormEvent) => {
    event?.preventDefault()
    if (await action.run(() => http.post(`/api/tasks/${taskId}/decide/`, { decision, note }))) onDecided()
  }
  return (
    <form className="stack" data-testid="decision-form" onSubmit={(e) => void decide('approve', e)}>
      <label className="field">
        <span>{t('workflow.note')}</span>
        <textarea rows={3} maxLength={5000} value={note} data-testid="decision-note" onChange={(e) => setNote(e.target.value)} />
      </label>
      <p className="muted">{t('workflow.returnRule')}</p>
      <div className="row">
        <button type="submit" className="primary-inline" disabled={action.busy} data-testid="decision-approve">
          {t('workflow.approve')}
        </button>
        <button type="button" className="secondary" disabled={action.busy} data-testid="decision-return" onClick={() => void decide('return')}>
          {t('workflow.return')}
        </button>
      </div>
      <ErrorMessage code={action.error} testId="decision-error" />
    </form>
  )
}

/** The version's way through its approval workflow (task 5.10), beside the content and the quality report: the
 * stages, the open task and its decision, why it was submitted with critical findings, and on a resubmission what
 * the authors say they fixed since the return (spec 6.2.7). */
export function ReviewPanel({ versionId, onChanged }: { versionId: number; onChanged: () => void }) {
  const { t } = useTranslation()
  const date = useDate()
  const workflow = useResource<{ submission: Submission | null }>(`/api/program-versions/${versionId}/workflow/`)
  const reopen = useAction()
  const submission = workflow.data?.submission
  if (!submission) return <ErrorMessage code={workflow.error} />
  const open = submission.tasks.find((task) => task.closed_at === null)
  const changed = () => {
    workflow.reload()
    onChanged()
  }

  return (
    <section className="panel review" data-testid="review-panel" data-outcome={submission.outcome}>
      <h2>{t('workflow.review')}</h2>
      <p className="muted">
        {t('workflow.submittedBy', { name: submission.submitted_by.full_name || submission.submitted_by.email, date: date(submission.created_at) })}
      </p>
      <ol className="stages-progress" data-testid="stages-progress">
        {submission.stages.map((stage) => {
          const state = open?.stage === stage.order ? 'current' : submission.decisions.some((d) => d.stage === stage.order && d.decision === 'approve') ? 'done' : 'upcoming'
          return (
            <li key={stage.order} data-state={state} className={`stage-${state}`}>
              {stage.name}
            </li>
          )
        })}
      </ol>

      {submission.pre_submit.reason && (
        <div className="notice" data-testid="pre-submit">
          <p>{t('workflow.submittedWithCritical', { count: submission.pre_submit.critical?.length ?? 0 })}</p>
          <p>
            <strong>{t('workflow.authorReason')}</strong> {submission.pre_submit.reason}
          </p>
        </div>
      )}

      {submission.previous && (
        <div data-testid="previous-submission">
          <h3>{t('workflow.previous', { number: submission.previous.version.number })}</h3>
          <Decisions decisions={submission.previous.decisions} testId="previous-decisions" />
        </div>
      )}

      {submission.resolved_must_fix.length > 0 && (
        <div data-testid="resolved-must-fix">
          <h3>{t('workflow.resolvedMustFix', { count: submission.resolved_must_fix.length })}</h3>
          <ul className="plain">
            {submission.resolved_must_fix.map((comment) => (
              <li key={comment.id} className="row" data-testid="resolved-comment">
                {comment.quoted && <q>{comment.quoted}</q>}
                <span>{comment.body}</span>
                <span className="muted">{t('workflow.resolvedBy', { name: comment.resolved_by?.full_name || comment.resolved_by?.email || '' })}</span>
                <button
                  type="button"
                  className="link-button"
                  data-testid="reopen-comment"
                  disabled={reopen.busy}
                  onClick={() => void reopen.run(() => http.post(`/api/comments/${comment.id}/reopen/`)).then((done) => done && changed())}
                >
                  {t('comments.reopen')}
                </button>
              </li>
            ))}
          </ul>
          <ErrorMessage code={reopen.error} />
        </div>
      )}

      {open && (
        <div data-testid="open-task">
          <TaskSummary task={open} onChanged={workflow.reload} />
          {open.permissions.can_decide && <DecisionForm taskId={open.id} onDecided={changed} />}
        </div>
      )}
      {submission.outcome && <p data-testid="review-outcome">{t(`workflow.outcome.${submission.outcome}`)}</p>}
      <Decisions decisions={submission.decisions} testId="decisions" />
    </section>
  )
}
