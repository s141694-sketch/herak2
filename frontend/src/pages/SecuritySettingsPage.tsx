import { type FormEvent, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'

import { api, http } from '../api'
import { useAuth } from '../auth'
import { ErrorMessage, Loading } from '../components/ErrorMessage'
import { useAction, useResource } from '../hooks/useResource'
import { leaveFor } from '../signIn'
import type { Member, UserRef } from '../types'

interface Domain {
  id: number
  domain: string
  record_name: string
  record_value: string
  verified_at: string | null
  last_error: string
  last_error_code: string
}

interface Provider {
  id: number
  issuer: string
  client_id: string
  has_secret: boolean
  enabled: boolean
  enforced: boolean
  emergency_user: UserRef | null
  discovery_ok_at: string | null
  test_login_ok_at: string | null
  tested: boolean
  last_test_error: string
  last_test_error_code: string
}

interface OrganizationRules {
  sso_session_hours: number
  mfa_required_for_managers: boolean
}

/** Why a check failed, translated, with the technical detail beside it for whoever sets up the provider or DNS. */
function Failure({ code, detail, testId }: { code: string; detail: string; testId?: string }) {
  const { t } = useTranslation()
  if (!code && !detail) return null
  return (
    <div className="error small" data-testid={testId}>
      <p role="alert">{t(`errors.${code || 'unknown'}`, { defaultValue: t('errors.unknown') })}</p>
      {detail && (
        <p className="muted" dir="ltr">
          {detail}
        </p>
      )}
    </div>
  )
}

/** After a change to who may sign in, the session is asked again: this admin may no longer enter (D66). */
function useRefreshSession() {
  const { setSession } = useAuth()
  return async () => setSession(await api.me())
}

function useDate() {
  const { i18n } = useTranslation()
  return (value: string | null) => (value ? new Date(value).toLocaleString(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }) : '')
}

function SignInRules() {
  const { t } = useTranslation()
  const organization = useResource<OrganizationRules>('/api/organizations/current/')
  const action = useAction()
  const refreshSession = useRefreshSession()
  const [hours, setHours] = useState<number | null>(null)
  const [saved, setSaved] = useState(false)
  if (!organization.data) return <ErrorMessage code={organization.error} />
  const current = organization.data
  const patch = async (body: Partial<OrganizationRules>) => {
    setSaved(false)
    if (await action.run(() => http.patch('/api/organizations/current/', body))) {
      organization.reload()
      setSaved(true)
      await refreshSession()
    }
  }
  return (
    <section className="panel" data-testid="sign-in-rules">
      <h2>{t('security.rules')}</h2>
      <label className="inline">
        <input
          type="checkbox"
          checked={current.mfa_required_for_managers}
          disabled={action.busy}
          data-testid="rules-mfa"
          onChange={(e) => void patch({ mfa_required_for_managers: e.target.checked })}
        />
        <span>{t('security.mfaForManagers')}</span>
      </label>
      <form
        className="row"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          void patch({ sso_session_hours: hours ?? current.sso_session_hours })
        }}
      >
        <label className="inline">
          <span>{t('security.sessionHours')}</span>
          <input
            type="number"
            min={1}
            max={168}
            value={hours ?? current.sso_session_hours}
            data-testid="rules-hours"
            onChange={(e) => setHours(Number(e.target.value))}
          />
        </label>
        <button type="submit" className="secondary" disabled={action.busy}>
          {t('common.save')}
        </button>
      </form>
      {saved && (
        <p className="muted" role="status">
          {t('security.saved')}
        </p>
      )}
      <ErrorMessage code={action.error} />
    </section>
  )
}

function Domains() {
  const { t } = useTranslation()
  const date = useDate()
  const domains = useResource<Domain[]>('/api/sso/domains/')
  const action = useAction()
  const [name, setName] = useState('')
  const add = async (event: FormEvent) => {
    event.preventDefault()
    if (await action.run(() => http.post('/api/sso/domains/', { domain: name }))) {
      setName('')
      domains.reload()
    }
  }
  return (
    <section className="panel" data-testid="sso-domains">
      <h2>{t('security.domains')}</h2>
      <p className="muted">{t('security.domainsIntro')}</p>
      <ul className="plain">
        {domains.data?.map((d) => (
          <li key={d.id} className="stack" data-testid="sso-domain" data-verified={Boolean(d.verified_at)}>
            <p className="row">
              <strong dir="ltr">{d.domain}</strong>
              {d.verified_at ? (
                <span className="badge badge-approved">{t('security.verifiedOn', { date: date(d.verified_at) })}</span>
              ) : (
                <span className="badge">{t('security.notVerified')}</span>
              )}
            </p>
            {!d.verified_at && (
              <>
                <p className="muted">{t('security.publishRecord')}</p>
                <p dir="ltr">
                  <code>{d.record_name}</code> {t('security.recordType')} <code>{d.record_value}</code>
                </p>
                <Failure code={d.last_error_code} detail={d.last_error} testId="sso-domain-failure" />
              </>
            )}
            <div className="row">
              {!d.verified_at && (
                <button
                  type="button"
                  className="secondary"
                  data-testid="sso-domain-verify"
                  disabled={action.busy}
                  onClick={() => void action.run(() => http.post(`/api/sso/domains/${d.id}/verify/`)).then(domains.reload)}
                >
                  {t('security.verify')}
                </button>
              )}
              <button
                type="button"
                className="link-button"
                disabled={action.busy}
                onClick={() => {
                  if (window.confirm(t('security.confirmRemoveDomain', { domain: d.domain })))
                    void action.run(() => http.del(`/api/sso/domains/${d.id}/`)).then(domains.reload)
                }}
              >
                {t('common.delete')}
              </button>
            </div>
          </li>
        ))}
      </ul>
      <form className="row" onSubmit={add}>
        <input
          required
          dir="ltr"
          aria-label={t('security.domain')}
          placeholder={t('security.domainPlaceholder')}
          value={name}
          data-testid="sso-domain-name"
          onChange={(e) => setName(e.target.value)}
        />
        <button type="submit" className="secondary" disabled={action.busy} data-testid="sso-domain-add">
          {t('common.add')}
        </button>
      </form>
      <ErrorMessage code={action.error} testId="sso-domain-error" />
    </section>
  )
}

function ProviderForm({ provider, onSaved }: { provider: Provider | null; onSaved: () => void }) {
  const { t } = useTranslation()
  const action = useAction()
  const [issuer, setIssuer] = useState(provider?.issuer ?? '')
  const [clientId, setClientId] = useState(provider?.client_id ?? '')
  const [secret, setSecret] = useState('')
  // The stored secret belongs to the provider and client it was given for: a new one needs its own (it is never
  // sent elsewhere).
  const moved = provider !== null && (issuer.trim() !== provider.issuer || clientId.trim() !== provider.client_id)
  const save = async (event: FormEvent) => {
    event.preventDefault()
    const body = { issuer, client_id: clientId, client_secret: secret }
    const done = await action.run(() => (provider ? http.put(`/api/sso/providers/${provider.id}/`, body) : http.post('/api/sso/providers/', body)))
    if (done) {
      setSecret('')
      onSaved()
    }
  }
  return (
    <form className="stack" onSubmit={save} data-testid="sso-provider-form">
      <label className="field">
        <span>{t('security.issuer')}</span>
        <input required dir="ltr" type="url" value={issuer} data-testid="sso-issuer" onChange={(e) => setIssuer(e.target.value)} />
      </label>
      <label className="field">
        <span>{t('security.clientId')}</span>
        <input required dir="ltr" value={clientId} data-testid="sso-client-id" onChange={(e) => setClientId(e.target.value)} />
      </label>
      <label className="field">
        <span>{t('security.clientSecret')}</span>
        <input
          type="password"
          dir="ltr"
          autoComplete="off"
          required={!provider?.has_secret || moved}
          placeholder={provider?.has_secret && !moved ? t('security.secretKept') : ''}
          value={secret}
          data-testid="sso-client-secret"
          onChange={(e) => setSecret(e.target.value)}
        />
      </label>
      {moved && <p className="muted small">{t('security.secretForNewProvider')}</p>}
      <p className="muted small">{t('security.changeClearsTests')}</p>
      <button type="submit" className="primary-inline" disabled={action.busy} data-testid="sso-provider-save">
        {t('common.save')}
      </button>
      <ErrorMessage code={action.error} testId="sso-provider-error" />
    </form>
  )
}

function ProviderPanel({ testResult }: { testResult: string | null }) {
  const { t, i18n } = useTranslation()
  const date = useDate()
  const providers = useResource<Provider[]>('/api/sso/providers/')
  const members = useResource<Member[]>('/api/organizations/current/members/')
  const action = useAction()
  const refreshSession = useRefreshSession()
  const [leaving, setLeaving] = useState(false)
  if (!providers.data) return <ErrorMessage code={providers.error} />
  const provider = providers.data[0] ?? null
  const admins = (members.data ?? []).filter((m) => m.role === 'admin')
  const busy = action.busy || leaving

  const testSignIn = async () => {
    const started = await action.run(() =>
      http.post<{ redirect: string }>(`/api/sso/providers/${provider!.id}/test-login/`, { language: i18n.language }),
    )
    if (!started) return
    setLeaving(true)
    try {
      leaveFor(started.redirect)
    } catch {
      setLeaving(false)
    }
  }
  const policy = async (change: Partial<{ enabled: boolean; enforced: boolean; emergency_user: number | null }>) => {
    const body = { enabled: provider!.enabled, enforced: provider!.enforced, emergency_user: provider!.emergency_user?.id ?? null, ...change }
    if (await action.run(() => http.post(`/api/sso/providers/${provider!.id}/policy/`, body))) {
      providers.reload()
      await refreshSession()
    }
  }
  // The result of the last test sign-in, while it still describes this provider (a change clears the test).
  const shownResult = testResult === 'ok' && !provider?.test_login_ok_at ? null : testResult

  return (
    <section className="panel" data-testid="sso-provider">
      <h2>{t('security.provider')}</h2>
      <p className="muted">{t('security.providerIntro')}</p>
      {shownResult && (
        <p className={shownResult === 'ok' ? 'notice' : 'error'} role="status" data-testid="sso-test-result" data-result={shownResult}>
          {shownResult === 'ok' ? t('security.testSignInDone') : t(`errors.${shownResult}`, { defaultValue: t('errors.unknown') })}
        </p>
      )}
      <ProviderForm key={provider ? `${provider.id}-${provider.issuer}-${provider.client_id}` : 'new'} provider={provider} onSaved={providers.reload} />
      {provider && (
        <>
          <h3>{t('security.tests')}</h3>
          <ul className="plain" data-testid="sso-tests">
            <li data-testid="sso-test-connection" data-ok={Boolean(provider.discovery_ok_at)}>
              {provider.discovery_ok_at ? t('security.connectionOk', { date: date(provider.discovery_ok_at) }) : t('security.connectionNotTested')}{' '}
              <button
                type="button"
                className="secondary"
                disabled={busy}
                data-testid="sso-test-connection-run"
                onClick={() => void action.run(() => http.post(`/api/sso/providers/${provider.id}/test/`)).then(providers.reload)}
              >
                {t('security.testConnection')}
              </button>
            </li>
            <li data-testid="sso-test-login" data-ok={Boolean(provider.test_login_ok_at)}>
              {provider.test_login_ok_at ? t('security.signInOk', { date: date(provider.test_login_ok_at) }) : t('security.signInNotTested')}{' '}
              <button type="button" className="secondary" disabled={busy} data-testid="sso-test-login-run" onClick={() => void testSignIn()}>
                {t('security.testSignIn')}
              </button>
            </li>
          </ul>
          <Failure code={provider.last_test_error_code} detail={provider.last_test_error} testId="sso-test-failure" />
          <h3>{t('security.policy')}</h3>
          <label className="inline">
            <input type="checkbox" checked={provider.enabled} disabled={busy} data-testid="sso-enabled" onChange={(e) => void policy({ enabled: e.target.checked, enforced: e.target.checked && provider.enforced })} />
            <span>{t('security.enabled')}</span>
          </label>
          <label className="inline">
            <span>{t('security.emergency')}</span>
            <select
              value={provider.emergency_user?.id ?? ''}
              disabled={busy}
              data-testid="sso-emergency"
              onChange={(e) => void policy({ emergency_user: e.target.value === '' ? null : Number(e.target.value) })}
            >
              <option value="">{t('security.chooseEmergency')}</option>
              {admins.map((m) => (
                <option key={m.user.id} value={m.user.id}>
                  {m.user.full_name || m.user.email}
                </option>
              ))}
            </select>
          </label>
          <p className="muted small">{t('security.emergencyHint')}</p>
          <label className="inline">
            <input type="checkbox" checked={provider.enforced} disabled={busy} data-testid="sso-enforced" onChange={(e) => void policy({ enforced: e.target.checked })} />
            <span>{t('security.enforced')}</span>
          </label>
          <p className="muted small">{t('security.enforcedHint')}</p>
        </>
      )}
      <ErrorMessage code={action.error} testId="sso-policy-error" />
    </section>
  )
}

/** Members' second factors (D67): an admin resets a lost one; the member sets it up again on next sign-in. */
function MemberFactors() {
  const { t } = useTranslation()
  const { session } = useAuth()
  const members = useResource<Member[]>('/api/organizations/current/members/')
  const action = useAction()
  const [reset, setReset] = useState<string | null>(null)
  const withFactor = (members.data ?? []).filter((m) => m.mfa_enabled && m.user.id !== session?.user.id)
  const resetFactor = async (member: Member) => {
    const name = member.user.full_name || member.user.email
    if (!window.confirm(t('security.confirmResetFactor', { name }))) return
    setReset(null)
    const done = await action.run(async () => {
      await http.post(`/api/organizations/current/members/${member.id}/reset-mfa/`)
      return true
    })
    if (done) {
      setReset(name)
      members.reload()
    }
  }
  return (
    <section className="panel" data-testid="member-factors">
      <h2>{t('security.memberFactors')}</h2>
      <p className="muted">{t('security.memberFactorsIntro')}</p>
      {withFactor.length === 0 ? (
        <p className="muted">{t('security.noMemberFactors')}</p>
      ) : (
        <ul className="plain">
          {withFactor.map((m) => (
            <li key={m.id} className="row" data-testid="member-factor">
              <span>{m.user.full_name || m.user.email}</span>
              <button type="button" className="link-button" disabled={action.busy} data-testid="member-factor-reset" onClick={() => void resetFactor(m)}>
                {t('security.resetFactor')}
              </button>
            </li>
          ))}
        </ul>
      )}
      {reset && (
        <p className="notice" role="status">
          {t('security.factorReset', { name: reset })}
        </p>
      )}
      <ErrorMessage code={action.error} testId="member-factor-error" />
    </section>
  )
}

/** The organization's sign-in security (task 6.9; spec 7.1, 7.2): rules, verified domains, its identity
 * provider with the connection test and a test sign-in, enforcement with its emergency account, and members'
 * second factors. */
export function SecuritySettingsPage() {
  const { t } = useTranslation()
  const { session } = useAuth()
  const [params, setParams] = useSearchParams()
  // The answer of a test sign-in, read once: a reload or a copied address does not repeat it.
  const [testResult] = useState(params.get('sso_test'))
  useEffect(() => {
    if (params.has('sso_test')) setParams({}, { replace: true })
  }, [params, setParams])
  if (!session?.organization) return <Loading />
  if (session.organization.role !== 'admin') return <ErrorMessage code="permission_denied" />
  return (
    <section className="card" data-testid="security-settings">
      <h1>{t('security.title')}</h1>
      <SignInRules />
      <Domains />
      <ProviderPanel testResult={testResult} />
      <MemberFactors />
    </section>
  )
}
