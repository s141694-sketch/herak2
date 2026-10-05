import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { api, errorCode } from '../api'
import { useAuth } from '../auth'
import { ErrorMessage } from '../components/ErrorMessage'

export function ChooseOrganizationPage() {
  const { t } = useTranslation()
  const { session, switchOrganization } = useAuth()
  const [error, setError] = useState<string | null>(null)
  if (!session) return null

  if (session.memberships.length === 0) {
    return (
      <section className="card" data-testid="no-membership">
        <h1>{t('organization.noMembershipTitle')}</h1>
        <p>{t('organization.noMembershipHint')}</p>
      </section>
    )
  }

  const enter = async (organizationId: number) => {
    setError(null)
    try {
      await switchOrganization(organizationId)
    } catch (caught) {
      setError(errorCode(caught))
    }
  }
  // An organization that enforces single sign-on is entered through its provider (D66).
  const throughProvider = async () => {
    setError(null)
    try {
      window.location.assign((await api.startSso(session.user.email)).redirect)
    } catch (caught) {
      setError(errorCode(caught))
    }
  }

  return (
    <section className="card" data-testid="choose-organization">
      <h1>{t('organization.chooseTitle')}</h1>
      <p>{t('organization.chooseHint')}</p>
      <ErrorMessage code={error} />
      <ul className="choices">
        {session.memberships.map((m) => (
          <li key={m.organization.id} data-testid="organization-choice" data-slug={m.organization.slug}>
            {m.sso_required ? (
              <button type="button" className="choice" onClick={() => void throughProvider()}>
                <strong>{m.organization.name}</strong>
                <span className="muted">{t('organization.ssoRequired')}</span>
              </button>
            ) : m.mfa_required ? (
              <Link to="/account/security" className="choice">
                <strong>{m.organization.name}</strong>
                <span className="muted">{t('organization.mfaRequired')}</span>
              </Link>
            ) : (
              <button type="button" className="choice" onClick={() => void enter(m.organization.id)}>
                <strong>{m.organization.name}</strong>
                <span className="muted">{t(`roles.${m.role}`)}</span>
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
