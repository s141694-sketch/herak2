import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ApiError } from '../api'
import { useAuth } from '../auth'
import { ErrorMessage } from './ErrorMessage'

/** The person's invitations not yet answered (D90): joining an organization takes their acceptance. Shown on every
 * page, before any organization is open as after. */
export function Invitations() {
  const { t } = useTranslation()
  const { session, setSession } = useAuth()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (!session || session.invitations.length === 0) return null

  const answer = async (id: number, choice: 'accept' | 'decline') => {
    setBusy(true)
    setError(null)
    try {
      setSession(await api.answerInvitation(id, choice))
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.code : 'network')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel" data-testid="invitations">
      <h2>{t('invitations.title')}</h2>
      <p className="muted">{t('invitations.hint')}</p>
      <ul className="choices">
        {session.invitations.map((invitation) => (
          <li key={invitation.id} data-testid="invitation" data-slug={invitation.organization.slug}>
            <span>
              {t('invitations.to', { name: invitation.organization.name, role: t(`roles.${invitation.role}`) })}
            </span>{' '}
            <button
              type="button"
              className="primary"
              disabled={busy}
              data-testid="invitation-accept"
              onClick={() => void answer(invitation.id, 'accept')}
            >
              {t('invitations.accept')}
            </button>{' '}
            <button
              type="button"
              disabled={busy}
              data-testid="invitation-decline"
              onClick={() => void answer(invitation.id, 'decline')}
            >
              {t('invitations.decline')}
            </button>
          </li>
        ))}
      </ul>
      <ErrorMessage code={error} testId="invitation-error" />
    </section>
  )
}
