import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'

import { http } from '../../api'
import { useAuth } from '../../auth'
import { ErrorMessage, Loading } from '../../components/ErrorMessage'
import { StatusBadge } from '../../components/StatusBadge'
import { useAction, useResource } from '../../hooks/useResource'
import type { Template } from '../../types'
import { type LevelDraft, LevelsEditor } from './LevelsEditor'

export function TemplateListPage() {
  const { t } = useTranslation()
  const { session } = useAuth()
  const navigate = useNavigate()
  const templates = useResource<Template[]>('/api/structure-templates/')
  const action = useAction()
  const [name, setName] = useState('')
  const [levels, setLevels] = useState<LevelDraft[]>([{ name_ar: '', name_en: '' }])
  const isAdmin = session?.organization?.role === 'admin'

  async function create(event: FormEvent) {
    event.preventDefault()
    const created = await action.run(() => http.post<Template>('/api/structure-templates/', { name, levels }))
    if (created) navigate(`/templates/${created.id}`)
  }

  return (
    <section className="card">
      <h1>{t('templates.title')}</h1>
      <ErrorMessage code={templates.error} />
      {templates.loading && <Loading />}
      <table className="table" data-testid="template-list">
        <tbody>
          {templates.data?.map((template) => {
            const latest = template.versions[template.versions.length - 1]
            return (
              <tr key={template.id}>
                <td>
                  <Link to={`/templates/${template.id}`}>{template.name}</Link>
                </td>
                <td>{latest && t('common.version', { number: latest.number })}</td>
                <td>{latest && <StatusBadge status={latest.status} />}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {templates.data?.length === 0 && <p className="muted">{t('common.empty')}</p>}

      {isAdmin && (
        <form className="stack" onSubmit={create} data-testid="new-template">
          <h2>{t('templates.new')}</h2>
          <label className="field">
            <span>{t('common.name')}</span>
            <input value={name} required data-testid="template-name" onChange={(event) => setName(event.target.value)} />
          </label>
          <h3>{t('templates.levels')}</h3>
          <LevelsEditor levels={levels} onChange={setLevels} />
          <ErrorMessage code={action.error} />
          <button type="submit" className="primary-inline" disabled={action.busy} data-testid="create-template">
            {t('common.create')}
          </button>
        </form>
      )}
    </section>
  )
}
