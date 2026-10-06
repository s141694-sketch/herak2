import { type FormEvent, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { api, errorCode } from '../api'
import { useAuth } from '../auth'
import { LanguageToggle } from '../components/LanguageToggle'
import { asciiDigits, leaveFor } from '../signIn'

/** Signing in (spec 7.1, 7.2): a password, then a code when the person uses a second factor; or through the
 * organization's identity provider, chosen by the email's domain. A refusal from the provider comes back here as
 * `?sso_error=<code>`; an organization that wants the password sends the person here with `?email=&reason=`. */
export function LoginPage() {
  const { t, i18n } = useTranslation()
  const { login, verifyMfa } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [email, setEmail] = useState(params.get('email') ?? '')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [step, setStep] = useState<'password' | 'code'>('password')
  const [error, setError] = useState<string | null>(params.get('sso_error') ?? params.get('reason'))
  const [submitting, setSubmitting] = useState(false)
  const [ssoAvailable, setSsoAvailable] = useState(false)

  // Spec 7.2: email, then its domain, then the organization's provider. Once an email is typed, the page learns
  // whether its organization signs people in through a provider, and offers that way first.
  useEffect(() => {
    setSsoAvailable(false)
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) return
    let current = true
    const timer = setTimeout(() => {
      api.discoverSso(email.trim()).then(
        ({ available }) => current && setSsoAvailable(available),
        () => undefined, // nothing to say: the password and the provider's button both still work
      )
    }, 400)
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [email])

  // Read once: a reload, or the address copied elsewhere, does not repeat the message.
  useEffect(() => {
    if (params.size) setParams({}, { replace: true })
  }, [params, setParams])

  /** Runs one step; ``leaving`` keeps the form busy while the browser goes to the provider's page. */
  async function attempt(action: () => Promise<'leaving' | void>) {
    setSubmitting(true)
    setError(null)
    try {
      if ((await action()) === 'leaving') return
    } catch (caught) {
      setError(errorCode(caught))
    }
    setSubmitting(false)
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
        // Too many tries or too late; or the organization wants its provider, whose button is on the first step.
        if (['mfa_not_pending', 'sso_required'].includes(errorCode(caught))) backToPassword()
        throw caught
      }
    })
  }

  const backToPassword = () => {
    setStep('password')
    setCode('')
    setPassword('')
  }

  const withOrganization = () =>
    void attempt(async () => {
      const { redirect } = await api.startSso({ email }, i18n.language)
      leaveFor(redirect)
      return 'leaving'
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
            <Link to="/forgot-password" className="small" data-testid="login-forgot">
              {t('login.forgot')}
            </Link>
            {error && (
              <p role="alert" className="error" data-testid="login-error">
                {t(`errors.${error}`, { defaultValue: t('errors.unknown') })}
              </p>
            )}
            {ssoAvailable && (
              <p className="notice" role="status" data-testid="sso-available">
                {t('login.ssoAvailable')}
              </p>
            )}
            <button type="submit" className={ssoAvailable ? 'secondary wide' : 'primary'} disabled={submitting}>
              {submitting ? t('login.submitting') : t('login.submit')}
            </button>
            <p className="login-or muted">{t('login.or')}</p>
            <button
              type="button"
              className={ssoAvailable ? 'primary' : 'secondary wide'}
              disabled={submitting || !email.includes('@')}
              data-testid="login-sso"
              onClick={withOrganization}
            >
              {t('login.withOrganization')}
            </button>
            {!ssoAvailable && <p className="muted small">{t('login.withOrganizationHint')}</p>}
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
                onChange={(event) => setCode(asciiDigits(event.target.value))}
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
            <button type="button" className="link-button" data-testid="mfa-back" onClick={backToPassword}>
              {t('login.back')}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
