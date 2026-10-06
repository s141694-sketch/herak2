import { useTranslation } from 'react-i18next'

import { useAuth } from '../auth'
import { ErrorMessage } from '../components/ErrorMessage'
import { entryHint, useEnterOrganization } from '../signIn'

export function ChooseOrganizationPage() {
  const { t } = useTranslation()
  const { session } = useAuth()
  const { enter, busy, error } = useEnterOrganization()
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
      <ErrorMessage code={error} />
      <ul className="choices">
        {session.memberships.map((m) => (
          <li key={m.organization.id} data-testid="organization-choice" data-slug={m.organization.slug}>
            <button type="button" className="choice" disabled={busy} onClick={() => void enter(m)}>
              <strong>{m.organization.name}</strong>
              <span className="muted">{t(entryHint(m))}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
