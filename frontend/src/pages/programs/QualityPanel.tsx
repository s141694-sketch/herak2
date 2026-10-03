import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type * as Y from 'yjs'

import { errorCode, http } from '../../api'
import { ErrorMessage } from '../../components/ErrorMessage'
import { useAction } from '../../hooks/useResource'
import type { BloomReading, Finding, QualityReport, Severity } from '../../types'

export const SEVERITIES: Severity[] = ['critical', 'warning', 'info']

/** Saves reach Django a couple of seconds after typing stops; the report is asked for again once they have. */
const AFTER_EDITS_MS = 4000
const WHILE_RUNNING_MS = 2000

/** The version's report: undefined while loading, null before its first check. */
export function useQualityReport(versionId: number, doc: Y.Doc | undefined) {
  const [report, setReport] = useState<QualityReport | null | undefined>(undefined)
  const load = useCallback(async () => {
    try {
      setReport(await http.get<QualityReport>(`/api/program-versions/${versionId}/quality/`))
    } catch (error) {
      if (errorCode(error) === 'report_not_found') setReport(null)
    }
  }, [versionId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!doc) return
    let timer: ReturnType<typeof setTimeout> | undefined
    const later = () => {
      clearTimeout(timer)
      timer = setTimeout(() => void load(), AFTER_EDITS_MS)
    }
    doc.on('update', later)
    return () => {
      doc.off('update', later)
      clearTimeout(timer)
    }
  }, [doc, load])

  useEffect(() => {
    if (report?.status !== 'running') return
    const timer = setTimeout(() => void load(), WHILE_RUNNING_MS)
    return () => clearTimeout(timer)
  }, [report, load])

  return { report, reload: load }
}

/** Counts by severity, only those above zero (the tree shows them on every node). */
export function RollupBadges({ counts, testId }: { counts: Record<Severity, number> | undefined; testId: string }) {
  const { t } = useTranslation()
  if (!counts) return null
  const shown = SEVERITIES.filter((severity) => counts[severity] > 0)
  if (shown.length === 0) return null
  return (
    <span className="rollup" data-testid={testId}>
      {shown.map((severity) => (
        <span key={severity} className={`badge severity-${severity}`} title={t(`quality.severity.${severity}`)}>
          {counts[severity]}
        </span>
      ))}
    </span>
  )
}

function useReading() {
  const { t } = useTranslation()
  return (reading: BloomReading | undefined) => {
    if (!reading?.domain) return t('quality.unclassified')
    const level = t(`quality.bloom.${reading.domain}.${reading.level_id}`, { defaultValue: reading.level })
    return t('quality.reading', { level, domain: t(`quality.domain.${reading.domain}`) })
  }
}

function message(t: (key: string, options?: Record<string, unknown>) => string, finding: Finding, reading: (r?: BloomReading) => string) {
  const p = finding.params
  const competency = finding.competency ? `${finding.competency.code} ${finding.competency.title}` : ''
  switch (finding.kind) {
    case 'competency_not_assessed':
      return t(p.has_objective ? 'quality.kinds.competency_not_assessed' : 'quality.kinds.competency_not_served', { competency })
    case 'objective_unmeasurable':
      return t('quality.kinds.objective_unmeasurable', { verb: p.verb })
    case 'objective_unclassified':
      return p.verb ? t('quality.kinds.objective_unclassified', { verb: p.verb }) : t('quality.kinds.objective_no_verb')
    case 'objective_components_missing':
      return t('quality.kinds.objective_components_missing', {
        missing: ((p.missing as string[]) ?? []).map((part) => t(`quality.components.${part}`)).join(t('quality.listSeparator')),
      })
    case 'possible_competency_match':
      return t('quality.kinds.possible_competency_match', { competency, score: Math.round(Number(p.score ?? 0) * 100) })
    case 'bloom_ai_level':
      return t('quality.kinds.bloom_ai_level', { ai: reading(p.ai as BloomReading) })
    case 'bloom_disagreement':
      return t('quality.kinds.bloom_disagreement')
    case 'competency_objective_suggestion':
      return t('quality.kinds.competency_objective_suggestion', { competency, objective: p.objective })
    default:
      return t(`quality.kinds.${finding.kind}`, { competency, defaultValue: finding.kind })
  }
}

function FindingItem({
  finding,
  where,
  canChange,
  onChanged,
}: {
  finding: Finding
  where: string
  canChange: boolean
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const reading = useReading()
  const action = useAction()
  const [dismissing, setDismissing] = useState(false)
  const [reason, setReason] = useState('')
  const run = async (path: string, body?: unknown) => {
    if ((await action.run(() => http.post(path, body))) !== undefined) onChanged()
  }
  return (
    <li className={`finding severity-${finding.severity}`} data-testid="quality-finding" data-kind={finding.kind} data-severity={finding.severity}>
      <p className="row">
        <span className={`badge severity-${finding.severity}`}>{t(`quality.severity.${finding.severity}`)}</span>
        <span className={finding.source === 'ai' ? 'badge badge-ai' : 'badge'}>{t(`quality.source.${finding.source}`)}</span>
        <span className="muted">{t(`suggestions.confidence.${finding.confidence}`)}</span>
      </p>
      <p>{message(t, finding, reading)}</p>
      {finding.kind === 'bloom_disagreement' && (
        <ul className="plain readings" data-testid="readings">
          <li>{t('quality.ruleReading', { reading: reading(finding.params.rule as BloomReading) })}</li>
          <li>{t('quality.aiReading', { reading: reading(finding.params.ai as BloomReading) })}</li>
        </ul>
      )}
      {finding.explanation && <p className="muted">{finding.explanation}</p>}
      {where && <p className="muted where">{where}</p>}
      {finding.dismissal && (
        <p className="muted" data-testid="finding-dismissal">
          {t('quality.dismissedBecause', { reason: finding.dismissal.reason, name: finding.dismissal.by?.name ?? '' })}
        </p>
      )}
      {canChange && !finding.dismissal && !dismissing && (
        <button type="button" className="link-button" data-testid="finding-dismiss" onClick={() => setDismissing(true)}>
          {t('quality.dismiss')}
        </button>
      )}
      {canChange && dismissing && (
        <form
          className="row"
          onSubmit={(event: FormEvent) => {
            event.preventDefault()
            void run(`/api/findings/${finding.id}/dismiss/`, { reason })
          }}
        >
          <input
            required
            maxLength={1000}
            aria-label={t('quality.dismissReason')}
            placeholder={t('quality.dismissReason')}
            value={reason}
            data-testid="finding-dismiss-reason"
            onChange={(e) => setReason(e.target.value)}
          />
          <button type="submit" className="secondary" disabled={action.busy} data-testid="finding-dismiss-confirm">
            {t('quality.dismiss')}
          </button>
          <button type="button" className="link-button" onClick={() => setDismissing(false)}>
            {t('common.cancel')}
          </button>
        </form>
      )}
      {canChange && finding.dismissal && (
        <button type="button" className="link-button" data-testid="finding-restore" disabled={action.busy} onClick={() => void run(`/api/findings/${finding.id}/restore/`)}>
          {t('quality.restore')}
        </button>
      )}
      <ErrorMessage code={action.error} />
    </li>
  )
}

/** The quality report beside the editor (task 4.10). */
export function QualityPanel({
  versionId,
  report,
  reload,
  canChange,
  describe,
}: {
  versionId: number
  report: QualityReport | null | undefined
  reload: () => void
  canChange: boolean
  /** Where a finding is: the node's title and the block's kind, as the tree shows them. */
  describe: (finding: Finding) => string
}) {
  const { t, i18n } = useTranslation()
  const action = useAction()
  const [showDismissed, setShowDismissed] = useState(false)

  const runFull = async () => {
    if ((await action.run(() => http.post(`/api/program-versions/${versionId}/quality/run/`))) !== undefined) reload()
  }
  const open = report?.findings.filter((finding) => !finding.dismissal) ?? []
  const dismissed = report?.findings.filter((finding) => finding.dismissal) ?? []
  const shown = showDismissed ? dismissed : open
  const ordered = SEVERITIES.flatMap((severity) => shown.filter((finding) => finding.severity === severity))

  return (
    <aside className="quality-panel" data-testid="quality-panel">
      <h2>{t('quality.title')}</h2>
      {report === undefined && <p className="muted">{t('common.loading')}</p>}
      {report === null && <p className="muted">{t('quality.none')}</p>}
      {report && (
        <>
          <p className="muted" data-testid="quality-status" data-status={report.status}>
            {t(`quality.status.${report.status}`)} · {t(`quality.run.${report.last_run}`)}
            {report.finished_at && ` · ${new Date(report.finished_at).toLocaleString(i18n.language)}`}
          </p>
          <p className="row quality-counts">
            {SEVERITIES.map((severity) => (
              <span key={severity} className={`badge severity-${severity}`}>
                {t(`quality.severity.${severity}`)}: <span data-testid={`quality-count-${severity}`}>{report.counts[severity] ?? 0}</span>
              </span>
            ))}
          </p>
        </>
      )}
      {canChange && (
        <button type="button" className="secondary" data-testid="quality-run" disabled={action.busy || report?.status === 'running'} onClick={() => void runFull()}>
          {t('quality.runFull')}
        </button>
      )}
      <ErrorMessage code={action.error} />
      {report && (
        <>
          {dismissed.length > 0 && (
            <p>
              <button type="button" className="link-button" data-testid="quality-show-dismissed" onClick={() => setShowDismissed((value) => !value)}>
                {showDismissed ? t('quality.showOpen', { count: open.length }) : t('quality.showDismissed', { count: dismissed.length })}
              </button>
            </p>
          )}
          {ordered.length === 0 && <p className="muted">{showDismissed ? t('quality.noneDismissed') : t('quality.noneOpen')}</p>}
          <ul className="plain findings">
            {ordered.map((finding) => (
              <FindingItem key={finding.id} finding={finding} where={describe(finding)} canChange={canChange} onChanged={reload} />
            ))}
          </ul>
        </>
      )}
    </aside>
  )
}
