import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router'

import { api, errorCode } from '../api'
import { useAuth } from '../auth'
import { LanguageToggle } from '../components/LanguageToggle'

/** Signing in (spec 7.1, 7.2): a password, then a code when the person uses a second factor; or through the
 * organization's identity provider, chosen by the email's domain. A refusal from the provider comes back here as
 * `?sso_error=<code>`. */
export function LoginPage() {
  const { t } = useTranslation()
  const { login, verifyMfa } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [step, setStep] = useState<'password' | 'code'>('password')
  const [error, setError] = useState<string | null>(params.get('sso_error'))
  const [submitting, setSubmitting] = useState(false)

  async function attempt(action: () => Promise<void>) {
    setSubmitting(true)
    setError(null)
    try {
      await action()
    } catch (caught) {
      setError(errorCode(caught))
    } finally {
      setSubmitting(false)
    }
  }

  const onPassword = (event: FormEvent) => {
    event.preventDefault()
    void attempt(async () => {
      if ((await login(email, password)) === 'mfa') setStep('code')
      else navigate('/', { replace: true })
    })
  }

  const onCode = (event: FormEvent) => {
    event.preventDefault()
    void attempt(async () => {
      try {
        await verifyMfa(code)
        navigate('/', { replace: true })
      } catch (caught) {
        if (errorCode(caught) === 'mfa_not_pending') setStep('password') // too many tries, or too late
        throw caught
      }
    })
  }

  const withOrganization = () =>
    void attempt(async () => {
      const { redirect } = await api.startSso(email)
      window.location.assign(redirect)
    })

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <h1 className="brand-title">{t('app.name')}</h1>
          <LanguageToggle />
        </div>
        <p className="muted">{t('app.tagline')}</p>
        <h2>{t('login.title')}</h2>
        {step === 'password' ? (
          <form onSubmit={onPassword} noValidate>
            <label className="field">
              <span>{t('login.email')}</span>
              <input
                name="email"
                type="email"
                dir="ltr"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <label className="field">
              <span>{t('login.password')}</span>
              <input
                name="password"
                type="password"
                dir="ltr"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {error && (
              <p role="alert" className="error" data-testid="login-error">
                {t(`errors.${error}`, { defaultValue: t('errors.unknown') })}
              </p>
            )}
            <button type="submit" className="primary" disabled={submitting}>
              {submitting ? t('login.submitting') : t('login.submit')}
            </button>
            <p className="login-or muted">{t('login.or')}</p>
            <button type="button" className="secondary wide" disabled={submitting || !email.includes('@')} data-testid="login-sso" onClick={withOrganization}>
              {t('login.withOrganization')}
            </button>
            <p className="muted small">{t('login.withOrganizationHint')}</p>
          </form>
        ) : (
          <form onSubmit={onCode} noValidate data-testid="mfa-step">
            <p>{t('login.codeHint')}</p>
            <label className="field">
              <span>{t('login.code')}</span>
              <input
                name="code"
                inputMode="numeric"
                autoComplete="one-time-code"
                dir="ltr"
                maxLength={6}
                required
                autoFocus
                value={code}
                data-testid="mfa-code"
                onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
              />
            </label>
            {error && (
              <p role="alert" className="error" data-testid="login-error">
                {t(`errors.${error}`, { defaultValue: t('errors.unknown') })}
              </p>
            )}
            <button type="submit" className="primary" disabled={submitting || code.length !== 6}>
              {t('login.verify')}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
