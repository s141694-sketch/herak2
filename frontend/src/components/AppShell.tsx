import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, useNavigate } from 'react-router'

import { useAuth } from '../auth'
import { LanguageToggle } from './LanguageToggle'
import { NotificationBell } from './NotificationBell'

export function AppShell({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const { session, logout, switchOrganization } = useAuth()
  const navigate = useNavigate()
  if (!session) return null

  return (
    <div className="shell">
      <header className="topbar">
        <NavLink to="/" className="brand">
          {t('app.name')}
        </NavLink>
        {session.organization && session.organization.role !== 'pending' && (
          <nav className="main-nav">
            <NavLink to="/programs" data-testid="nav-programs">
              {t('nav.programs')}
            </NavLink>
            <NavLink to="/competencies" data-testid="nav-competencies">
              {t('nav.competencies')}
            </NavLink>
            <NavLink to="/templates" data-testid="nav-templates">
              {t('nav.templates')}
            </NavLink>
            <NavLink to="/workflows" data-testid="nav-workflows">
              {t('nav.workflows')}
            </NavLink>
            <NavLink to="/tasks" data-testid="nav-tasks">
              {t('nav.tasks')}
            </NavLink>
            {session.organization.role === 'admin' && (
              <NavLink to="/settings/security" data-testid="nav-security">
                {t('nav.security')}
              </NavLink>
            )}
          </nav>
        )}
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
        {session.organization && session.organization.role !== 'pending' && <NotificationBell key={session.organization.id} />}
        <NavLink to="/account/security" data-testid="user-name" title={t('nav.accountSecurity')}>
          {session.user.full_name || session.user.email}
        </NavLink>
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
