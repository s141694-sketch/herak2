import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router'

import { http } from '../../api'
import { useAuth } from '../../auth'
import { ErrorMessage, Loading } from '../../components/ErrorMessage'
import { StatusBadge } from '../../components/StatusBadge'
import { useAction, useResource } from '../../hooks/useResource'
import type { Collaborator, Program, ProgramVersionSummary } from '../../types'
import { ProgramWorkflow } from '../workflows/ProgramWorkflow'

export function ProgramPage() {
  const { t } = useTranslation()
  const { session } = useAuth()
  const { id } = useParams()
  const navigate = useNavigate()
  const program = useResource<Program>(`/api/programs/${id}/`)
  const collaborators = useResource<Collaborator[]>(`/api/programs/${id}/collaborators/`)
  const action = useAction()
  const [email, setEmail] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')

  if (program.loading && !program.data) return <Loading />
  if (!program.data) return <ErrorMessage code={program.error} />
  const { permissions, versions } = program.data
  const latest = versions[versions.length - 1]
  const comparable = versions.length > 1

  async function addCollaborator(event: FormEvent) {
    event.preventDefault()
    const added = await action.run(() => http.post(`/api/programs/${id}/collaborators/`, { user_email: email }))
    if (added) {
      setEmail('')
      collaborators.reload()
    }
  }

  return (
    <section className="card">
      <h1 data-testid="program-heading">{program.data.title}</h1>
      <p className="muted">
        {program.data.target_role} <StatusBadge status={program.data.status} />
      </p>
      <ErrorMessage code={action.error} />

      <h2>{t('common.versions')}</h2>
      <table className="table" data-testid="program-versions">
        <tbody>
          {versions.map((v: ProgramVersionSummary) => (
            <tr key={v.id} data-version={v.number}>
              <td>
                <Link to={`/program-versions/${v.id}`}>{t('common.version', { number: v.number })}</Link>
              </td>
              <td>
                <StatusBadge status={v.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {permissions.edit && latest && ['approved', 'exported', 'cancelled'].includes(latest.status) && (
        <button
          type="button"
          className="secondary"
          data-testid="new-program-version"
          onClick={() =>
            void action.run(() => http.post<ProgramVersionSummary>(`/api/programs/${id}/versions/`)).then((created) => {
              if (created) navigate(`/program-versions/${created.id}`)
            })
          }
        >
          {t('common.newVersion')}
        </button>
      )}

      {comparable && (
        <div className="row" data-testid="compare">
          <strong>{t('programs.compare')}</strong>
          <label>
            {t('programs.compareFrom')}{' '}
            <select value={from} data-testid="compare-from" onChange={(e) => setFrom(e.target.value)}>
              <option value="" />
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  {t('common.version', { number: v.number })}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t('programs.compareTo')}{' '}
            <select value={to} data-testid="compare-to" onChange={(e) => setTo(e.target.value)}>
              <option value="" />
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  {t('common.version', { number: v.number })}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="secondary"
            disabled={!from || !to}
            data-testid="compare-go"
            onClick={() => navigate(`/programs/${id}/diff/${from}/${to}`)}
          >
            {t('programs.compareGo')}
          </button>
        </div>
      )}

      <ProgramWorkflow
        programId={program.data.id}
        canChoose={(permissions.edit || session?.organization?.role === 'admin') && versions.some((v) => v.status === 'draft')}
      />

      <h2>{t('programs.collaborators')}</h2>
      <ul className="plain" data-testid="collaborators">
        {collaborators.data?.map((c) => (
          <li key={c.id}>
            {c.user.full_name || c.user.email} <span className="muted" dir="ltr">{c.user.email}</span>
            {permissions.manage && c.user.id !== program.data?.owner.id && (
              <button
                type="button"
                className="link-button"
                onClick={() => void action.run(() => http.del(`/api/program-collaborators/${c.id}/`)).then(collaborators.reload)}
              >
                {t('programs.remove')}
              </button>
            )}
          </li>
        ))}
      </ul>
      {permissions.manage && (
        <form className="row" onSubmit={addCollaborator}>
          <input
            type="email"
            dir="ltr"
            required
            aria-label={t('programs.collaboratorEmail')}
            placeholder={t('programs.collaboratorEmail')}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <button type="submit" className="secondary" disabled={action.busy}>
            {t('programs.addCollaborator')}
          </button>
        </form>
      )}
    </section>
  )
}
