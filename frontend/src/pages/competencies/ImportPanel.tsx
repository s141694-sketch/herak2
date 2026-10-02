import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { http } from '../../api'
import { ErrorMessage } from '../../components/ErrorMessage'
import { useAction } from '../../hooks/useResource'
import type { CompetencyImport } from '../../types'

export function ImportPanel({ versionId, onApplied }: { versionId: number; onApplied: () => void }) {
  const { t } = useTranslation()
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<CompetencyImport | null>(null)
  const [applied, setApplied] = useState(false)
  const action = useAction()

  async function upload() {
    if (!file) return
    setApplied(false)
    const result = await action.run(() => http.upload<CompetencyImport>(`/api/framework-versions/${versionId}/imports/`, file))
    if (result) setPreview(result)
  }

  async function confirm() {
    if (!preview) return
    const result = await action.run(() => http.post<CompetencyImport>(`/api/competency-imports/${preview.id}/confirm/`))
    if (result) {
      setPreview(null)
      setApplied(true)
      onApplied()
    }
  }

  return (
    <div className="panel" data-testid="import-panel">
      <h3>{t('import.title')}</h3>
      <p className="muted">{t('import.hint')}</p>
      <div className="row">
        <input
          type="file"
          accept=".csv,.xlsx"
          aria-label={t('import.choose')}
          data-testid="import-file"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <button type="button" className="secondary" disabled={!file || action.busy} data-testid="import-upload" onClick={() => void upload()}>
          {t('import.upload')}
        </button>
      </div>
      <ErrorMessage code={action.error} testId="import-error" />
      {applied && <p className="notice">{t('import.applied')}</p>}
      {preview && (
        <>
          <p data-testid="import-summary">{t('import.summary', preview.summary)}</p>
          <table className="table" data-testid="import-preview">
            <thead>
              <tr>
                <th>{t('import.row')}</th>
                <th>{t('frameworks.code')}</th>
                <th>{t('frameworks.competencyTitle')}</th>
                <th>{t('frameworks.requirement')}</th>
                <th>{t('import.action')}</th>
                <th>{t('import.errors')}</th>
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row) => (
                <tr key={row.row} className={row.errors.length ? 'row-error' : undefined}>
                  <td>{row.row}</td>
                  <td dir="ltr">{row.values.code}</td>
                  <td>{row.values.title}</td>
                  <td>{row.errors.includes('invalid_requirement') ? row.values.requirement : t(`requirement.${row.values.requirement}`)}</td>
                  <td>{t(`importAction.${row.action}`)}</td>
                  <td>{row.errors.map((code) => t(`importError.${code}`)).join('، ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            type="button"
            className="primary-inline"
            disabled={preview.summary.errors > 0 || action.busy}
            data-testid="import-confirm"
            onClick={() => void confirm()}
          >
            {t('import.confirm')}
          </button>
        </>
      )}
    </div>
  )
}
