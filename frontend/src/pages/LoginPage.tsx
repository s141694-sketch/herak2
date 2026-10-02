import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { errorCode } from '../api'
import { useAuth } from '../auth'
import { LanguageToggle } from '../components/LanguageToggle'

export function LoginPage() {
  const { t } = useTranslation()
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await login(email, password)
      navigate('/', { replace: true })
    } catch (caught) {
      setError(errorCode(caught))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <h1 className="brand-title">{t('app.name')}</h1>
          <LanguageToggle />
        </div>
        <p className="muted">{t('app.tagline')}</p>
        <h2>{t('login.title')}</h2>
        <form onSubmit={onSubmit} noValidate>
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
              {t(`errors.${error}`)}
            </p>
          )}
          <button type="submit" className="primary" disabled={submitting}>
            {submitting ? t('login.submitting') : t('login.submit')}
          </button>
        </form>
      </div>
    </div>
  )
}
