import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { http } from '../api'
import { useAuth } from '../auth'
import { ErrorMessage, Loading } from '../components/ErrorMessage'
import { useAction, useResource } from '../hooks/useResource'

interface Member {
  id: number
  user: { id: number; email: string; full_name: string }
  role: string
  /** An invitation shows its email alone until the person accepts it (D90). */
  status: 'member' | 'invited'
  mfa_enabled?: boolean
}

const ROLES = ['admin', 'author', 'reviewer', 'approver', 'pending'] as const

/** The organization's members (spec 2.1, D87): an admin invites people by email with a role, and changes roles.
 * Joining takes the person's acceptance (D90): until then the row is an invitation, which the admin may cancel. */
export function MembersPage() {
  const { t } = useTranslation()
  const { session, refresh } = useAuth()
  const members = useResource<Member[]>('/api/organizations/current/members/')
  const action = useAction()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<string>('author')
  const [added, setAdded] = useState<string | null>(null)
  if (!session?.organization) return <Loading />
  if (session.organization.role !== 'admin') return <ErrorMessage code="permission_denied" />
  if (!members.data) return <ErrorMessage code={members.error} />

  const add = async (event: FormEvent) => {
    event.preventDefault()
    setAdded(null)
    const done = await action.run(() =>
      http.post('/api/organizations/current/members/', { email: email.trim(), full_name: name.trim(), role }),
    )
    if (done) {
      setAdded(email.trim())
      setEmail('')
      setName('')
      members.reload()
    }
  }
  const change = async (member: Member, next: string) => {
    setAdded(null)
    if (!(await action.run(() => http.patch(`/api/organizations/current/members/${member.id}/`, { role: next })))) return
    // One's own role: the menu and this page follow the session, read again (phase 8 review).
    if (member.user.id === session?.user.id) await refresh()
    else members.reload()
  }
  const cancel = async (member: Member) => {
    setAdded(null)
    // The answer has no body (204): a failure is what returns undefined.
    const done = await action.run(async () => {
      await http.del(`/api/organizations/current/members/${member.id}/`)
      return true
    })
    if (done) members.reload()
  }

  return (
    <section className="card" data-testid="members">
      <h1>{t('members.title')}</h1>
      <p className="muted">{t('members.intro')}</p>
      <table className="table" data-testid="member-list">
        <thead>
          <tr>
            <th>{t('members.person')}</th>
            <th>{t('members.role')}</th>
            <th>{t('members.secondFactor')}</th>
          </tr>
        </thead>
        <tbody>
          {members.data.map((member) => (
            <tr key={member.id} data-testid="member" data-email={member.user.email} data-status={member.status}>
              <td>
                {member.user.full_name || member.user.email}{' '}
                <span className="muted" dir="ltr">
                  {member.user.email}
                </span>
                {member.status === 'invited' && (
                  <>
                    {' '}
                    <span className="badge" data-testid="member-invited">
                      {t('members.invited')}
                    </span>{' '}
                    <button
                      type="button"
                      className="link-button"
                      disabled={action.busy}
                      data-testid="member-cancel"
                      onClick={() => void cancel(member)}
                    >
                      {t('members.cancel')}
                    </button>
                  </>
                )}
              </td>
              <td>
                <select
                  aria-label={t('members.roleOf', { name: member.user.full_name || member.user.email })}
                  value={member.role}
                  disabled={action.busy}
                  data-testid="member-role"
                  onChange={(event) => void change(member, event.target.value)}
                >
                  {ROLES.map((value) => (
                    <option key={value} value={value}>
                      {t(`roles.${value}`)}
                    </option>
                  ))}
                </select>
              </td>
              <td>{member.status === 'invited' ? '—' : member.mfa_enabled ? t('members.on') : t('members.off')}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <form className="panel" onSubmit={add} data-testid="member-add">
        <h2>{t('members.add')}</h2>
        <p className="muted">{t('members.addHint')}</p>
        <label className="field">
          <span>{t('members.email')}</span>
          <input type="email" dir="ltr" required value={email} data-testid="member-email" onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span>{t('members.name')}</span>
          <input value={name} data-testid="member-name" onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span>{t('members.role')}</span>
          <select value={role} data-testid="member-new-role" onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((value) => (
              <option key={value} value={value}>
                {t(`roles.${value}`)}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="primary" disabled={action.busy} data-testid="member-add-submit">
          {t('members.addSubmit')}
        </button>
      </form>
      {added && (
        <p className="notice" role="status" data-testid="member-added">
          {t('members.added', { email: added })}
        </p>
      )}
      <ErrorMessage code={action.error} testId="member-error" />
    </section>
  )
}
