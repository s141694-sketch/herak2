import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { http } from '../../api'
import { useAuth } from '../../auth'
import { ErrorMessage } from '../../components/ErrorMessage'
import { useAction, useResource } from '../../hooks/useResource'

interface ExportState {
  status: 'none' | 'pending' | 'running' | 'done' | 'failed'
  attempts?: number
  word?: { id: number; name: string } | null
  pdf?: { id: number; name: string } | null
  last_error?: string
}

/** The Word and PDF files of an approved version (tasks 7.5, 7.6; spec 2.2 publishing). They are made in the
 * background after the approval: the panel follows until they are ready, and an admin tries a failed export
 * again. The approval stands either way (spec 7.7). */
export function ExportPanel({ versionId }: { versionId: number }) {
  const { t } = useTranslation()
  const { session } = useAuth()
  const exported = useResource<ExportState>(`/api/program-versions/${versionId}/export/`)
  const action = useAction()
  const status = exported.data?.status
  const waiting = status === 'none' || status === 'pending' || status === 'running'
  const { reload } = exported
  useEffect(() => {
    if (!waiting) return
    const timer = setInterval(reload, 3000)
    return () => clearInterval(timer)
  }, [waiting, reload])
  if (!exported.data) return <ErrorMessage code={exported.error} />
  const data = exported.data

  return (
    <section className="panel" data-testid="export-panel" data-status={data.status}>
      <h2>{t('export.title')}</h2>
      {waiting && (
        <p className="muted" role="status">
          {t('export.making')}
        </p>
      )}
      {data.status === 'done' && (
        <div className="row">
          {data.word && (
            <a className="secondary download" href={`/api/files/${data.word.id}/download/`} data-testid="export-word">
              {t('export.word')}
            </a>
          )}
          {data.pdf && (
            <a className="secondary download" href={`/api/files/${data.pdf.id}/download/`} data-testid="export-pdf">
              {t('export.pdf')}
            </a>
          )}
        </div>
      )}
      {data.status === 'failed' && (
        <div role="alert" className="error" data-testid="export-failed">
          <p>{t('export.failed')}</p>
          {data.last_error && (
            <p className="muted small" dir="ltr">
              {data.last_error}
            </p>
          )}
          {session?.organization?.role === 'admin' && (
            <button
              type="button"
              className="secondary"
              disabled={action.busy}
              data-testid="export-retry"
              onClick={() => void action.run(() => http.post(`/api/program-versions/${versionId}/export/retry/`)).then(reload)}
            >
              {t('export.retry')}
            </button>
          )}
        </div>
      )}
      <ErrorMessage code={action.error} testId="export-error" />
    </section>
  )
}
