import { useTranslation } from 'react-i18next'

import { Link } from 'react-router'

import { useAuth } from '../auth'

export function HomePage() {
  const { t } = useTranslation()
  const { session } = useAuth()
  if (!session?.organization) return null
  const { organization, user } = session

  return (
    <section className="card" data-testid="home">
      <h1>{t('home.welcome', { name: user.full_name || user.email })}</h1>
      <dl className="facts">
        <dt>{t('home.currentOrganization')}</dt>
        <dd data-testid="current-organization">{organization.name}</dd>
        <dt>{t('home.yourRole')}</dt>
        <dd data-testid="current-role">{t(`roles.${organization.role}`)}</dd>
      </dl>
      {organization.role === 'pending' ? (
        <p className="notice">{t('home.pendingHint')}</p>
      ) : (
        <ul className="plain quick-links">
          <li>
            <Link to="/programs">{t('nav.programs')}</Link>
          </li>
          <li>
            <Link to="/competencies">{t('nav.competencies')}</Link>
          </li>
          <li>
            <Link to="/templates">{t('nav.templates')}</Link>
          </li>
        </ul>
      )}
    </section>
  )
}
