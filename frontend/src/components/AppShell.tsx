import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { useAuth } from '../auth'
import { LanguageToggle } from './LanguageToggle'

export function AppShell({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const { session, logout, switchOrganization } = useAuth()
  const navigate = useNavigate()
  if (!session) return null

  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">{t('app.name')}</span>
        {session.memberships.length > 1 && (
          <label className="switcher">
            <span>{t('organization.switcher')}</span>
            <select
              data-testid="organization-switcher"
              value={session.organization?.id ?? ''}
              onChange={(event) => void switchOrganization(Number(event.target.value))}
            >
              {!session.organization && <option value="">{t('organization.none')}</option>}
              {session.memberships.map((m) => (
                <option key={m.organization.id} value={m.organization.id}>
                  {m.organization.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <span className="spacer" />
        <span data-testid="user-name">{session.user.full_name || session.user.email}</span>
        <LanguageToggle />
        <button
          type="button"
          className="link-button"
          data-testid="logout"
          onClick={() => void logout().then(() => navigate('/login', { replace: true }))}
        >
          {t('nav.logout')}
        </button>
      </header>
      <main className="content">{children}</main>
    </div>
  )
}
