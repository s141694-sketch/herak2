import { type ReactNode, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, useNavigate, useSearchParams } from 'react-router'

import { useAuth } from '../auth'
import { entryHint, useEnterOrganization } from '../signIn'
import { ErrorMessage } from './ErrorMessage'
import { Invitations } from './Invitations'
import { LanguageToggle } from './LanguageToggle'
import { NotificationBell } from './NotificationBell'

/** Why an identity provider refused, for a browser that was already signed in (the server sends it to its own
 * page with ?sso_error=). Read once, then taken out of the address so a reload does not repeat it. */
function ProviderRefusal() {
  const [params, setParams] = useSearchParams()
  const [code] = useState(params.get('sso_error'))
  useEffect(() => {
    if (params.has('sso_error')) {
      const rest = new URLSearchParams(params)
      rest.delete('sso_error')
      setParams(rest, { replace: true })
    }
  }, [params, setParams])
  return <ErrorMessage code={code} testId="sso-refusal" />
}

export function AppShell({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const { session, logout } = useAuth()
  const navigate = useNavigate()
  const { enter, busy, error } = useEnterOrganization()
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
              <>
                <NavLink to="/settings/security" data-testid="nav-security">
                  {t('nav.security')}
                </NavLink>
                <NavLink to="/settings/identity" data-testid="nav-identity">
                  {t('nav.identity')}
                </NavLink>
                <NavLink to="/settings/members" data-testid="nav-members">
                  {t('nav.members')}
                </NavLink>
              </>
            )}
          </nav>
        )}
        {session.memberships.length > 1 && (
          <label className="switcher">
            <span>{t('organization.switcher')}</span>
            <select
              data-testid="organization-switcher"
              value={session.organization?.id ?? ''}
              disabled={busy}
              onChange={(event) => {
                const chosen = session.memberships.find((m) => m.organization.id === Number(event.target.value))
                if (chosen) void enter(chosen)
              }}
            >
              {!session.organization && <option value="">{t('organization.none')}</option>}
              {session.memberships.map((m) => (
                <option key={m.organization.id} value={m.organization.id}>
                  {m.sso_required || m.password_required || m.mfa_required
                    ? t('organization.optionWithHint', { name: m.organization.name, hint: t(entryHint(m)) })
                    : m.organization.name}
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
      <main className="content">
        <ErrorMessage code={error} testId="switch-error" />
        <ProviderRefusal />
        <Invitations />
        {children}
      </main>
    </div>
  )
}
