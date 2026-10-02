import { useTranslation } from 'react-i18next'

import { useAuth } from '../auth'

export function ChooseOrganizationPage() {
  const { t } = useTranslation()
  const { session, switchOrganization } = useAuth()
  if (!session) return null

  if (session.memberships.length === 0) {
    return (
      <section className="card" data-testid="no-membership">
        <h1>{t('organization.noMembershipTitle')}</h1>
        <p>{t('organization.noMembershipHint')}</p>
      </section>
    )
  }

  return (
    <section className="card" data-testid="choose-organization">
      <h1>{t('organization.chooseTitle')}</h1>
      <p>{t('organization.chooseHint')}</p>
      <ul className="choices">
        {session.memberships.map((m) => (
          <li key={m.organization.id}>
            <button type="button" className="choice" onClick={() => void switchOrganization(m.organization.id)}>
              <strong>{m.organization.name}</strong>
              <span className="muted">{t(`roles.${m.role}`)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
