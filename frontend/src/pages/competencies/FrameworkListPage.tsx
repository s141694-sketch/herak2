import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'

import { http } from '../../api'
import { useAuth } from '../../auth'
import { ErrorMessage, Loading } from '../../components/ErrorMessage'
import { StatusBadge } from '../../components/StatusBadge'
import { useAction, useResource } from '../../hooks/useResource'
import type { Framework } from '../../types'

export function FrameworkListPage() {
  const { t } = useTranslation()
  const { session } = useAuth()
  const navigate = useNavigate()
  const frameworks = useResource<Framework[]>('/api/competency-frameworks/')
  const action = useAction()
  const [name, setName] = useState('')
  const isAdmin = session?.organization?.role === 'admin'

  async function create(event: FormEvent) {
    event.preventDefault()
    const created = await action.run(() => http.post<Framework>('/api/competency-frameworks/', { name }))
    if (created) navigate(`/competencies/${created.id}`)
  }

  return (
    <section className="card">
      <h1>{t('frameworks.title')}</h1>
      <ErrorMessage code={frameworks.error} />
      {frameworks.loading && <Loading />}
      <table className="table" data-testid="framework-list">
        <tbody>
          {frameworks.data?.map((framework) => {
            const latest = framework.versions[framework.versions.length - 1]
            return (
              <tr key={framework.id}>
                <td>
                  <Link to={`/competencies/${framework.id}`}>{framework.name}</Link>
                </td>
                <td>{latest && t('common.version', { number: latest.number })}</td>
                <td>{latest && <StatusBadge status={latest.status} />}</td>
                <td>{latest && t('frameworks.count', { count: latest.competency_count })}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {frameworks.data?.length === 0 && <p className="muted">{t('common.empty')}</p>}
      {isAdmin && (
        <form className="row" onSubmit={create} data-testid="new-framework">
          <input
            aria-label={t('common.name')}
            placeholder={t('frameworks.new')}
            value={name}
            required
            data-testid="framework-name"
            onChange={(event) => setName(event.target.value)}
          />
          <button type="submit" className="primary-inline" disabled={action.busy} data-testid="create-framework">
            {t('common.create')}
          </button>
        </form>
      )}
      <ErrorMessage code={action.error} />
    </section>
  )
}
