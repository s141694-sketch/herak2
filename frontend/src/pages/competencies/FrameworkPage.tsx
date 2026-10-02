import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router'

import { http } from '../../api'
import { useAuth } from '../../auth'
import { ErrorMessage, Loading } from '../../components/ErrorMessage'
import { StatusBadge } from '../../components/StatusBadge'
import { useAction, useResource } from '../../hooks/useResource'
import type { Competency, Framework, FrameworkVersionDetail } from '../../types'
import { ImportPanel } from './ImportPanel'

const EMPTY = { code: '', title: '', level: '', requirement: 'required' as Competency['requirement'] }

export function FrameworkPage() {
  const { t } = useTranslation()
  const { id } = useParams()
  const { session } = useAuth()
  const isAdmin = session?.organization?.role === 'admin'
  const framework = useResource<Framework>(`/api/competency-frameworks/${id}/`)
  const [selected, setSelected] = useState<number | null>(null)
  const versionId = selected ?? framework.data?.versions[framework.data.versions.length - 1]?.id ?? null
  const version = useResource<FrameworkVersionDetail>(versionId ? `/api/framework-versions/${versionId}/` : null)
  const action = useAction()
  const [form, setForm] = useState(EMPTY)

  const refresh = () => {
    framework.reload()
    version.reload()
  }

  async function addCompetency(event: FormEvent) {
    event.preventDefault()
    const created = await action.run(() => http.post(`/api/framework-versions/${versionId}/competencies/`, form))
    if (created) {
      setForm(EMPTY)
      refresh()
    }
  }

  if (framework.loading && !framework.data) return <Loading />
  if (!framework.data) return <ErrorMessage code={framework.error} />
  const draft = version.data?.status === 'draft'
  const hasDraft = framework.data.versions.some((v) => v.status === 'draft')

  return (
    <section className="card">
      <h1>{framework.data.name}</h1>
      <div className="tabs" data-testid="framework-versions">
        {framework.data.versions.map((v) => (
          <button key={v.id} type="button" className={v.id === versionId ? 'tab active' : 'tab'} onClick={() => setSelected(v.id)}>
            {t('common.version', { number: v.number })} <StatusBadge status={v.status} />
          </button>
        ))}
      </div>
      <ErrorMessage code={version.error ?? action.error} />
      {version.data && (
        <>
          <h2>{t('frameworks.competencies')}</h2>
          <table className="table" data-testid="competency-table">
            <thead>
              <tr>
                <th>{t('frameworks.code')}</th>
                <th>{t('frameworks.competencyTitle')}</th>
                <th>{t('frameworks.level')}</th>
                <th>{t('frameworks.requirement')}</th>
              </tr>
            </thead>
            <tbody>
              {version.data.competencies.map((c) => (
                <tr key={c.id}>
                  <td dir="ltr">{c.code}</td>
                  <td>{c.title}</td>
                  <td>{c.level}</td>
                  <td>{t(`requirement.${c.requirement}`)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {version.data.competencies.length === 0 && <p className="muted">{t('common.empty')}</p>}

          {draft && isAdmin && (
            <>
              <form className="row" onSubmit={addCompetency} data-testid="add-competency">
                <input aria-label={t('frameworks.code')} placeholder={t('frameworks.code')} dir="ltr" required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
                <input aria-label={t('frameworks.competencyTitle')} placeholder={t('frameworks.competencyTitle')} required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
                <input aria-label={t('frameworks.level')} placeholder={t('frameworks.level')} value={form.level} onChange={(e) => setForm({ ...form, level: e.target.value })} />
                <select aria-label={t('frameworks.requirement')} value={form.requirement} onChange={(e) => setForm({ ...form, requirement: e.target.value as Competency['requirement'] })}>
                  <option value="required">{t('requirement.required')}</option>
                  <option value="optional">{t('requirement.optional')}</option>
                </select>
                <button type="submit" className="secondary" disabled={action.busy}>
                  {t('frameworks.addCompetency')}
                </button>
              </form>
              <ImportPanel versionId={version.data.id} onApplied={refresh} />
              <button
                type="button"
                className="primary-inline"
                disabled={action.busy}
                data-testid="publish-framework"
                onClick={() => void action.run(() => http.post(`/api/framework-versions/${versionId}/publish/`)).then(refresh)}
              >
                {t('common.publish')}
              </button>
            </>
          )}
          {!draft && isAdmin && !hasDraft && (
            <div className="row">
              <p className="muted">{t('frameworks.noDraftHint')}</p>
              <button
                type="button"
                className="secondary"
                data-testid="new-framework-version"
                onClick={() =>
                  void action.run(() => http.post(`/api/competency-frameworks/${id}/versions/`)).then((created) => {
                    if (created) {
                      setSelected(null)
                      refresh()
                    }
                  })
                }
              >
                {t('common.newVersion')}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
