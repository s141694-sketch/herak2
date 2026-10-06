import { type FormEvent, type ReactNode, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'

import { http } from '../api'
import { LanguageToggle } from '../components/LanguageToggle'
import { ErrorMessage } from '../components/ErrorMessage'
import { useAction } from '../hooks/useResource'

function Card({ title, children }: { title: string; children: ReactNode }) {
  const { t } = useTranslation()
  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <h1 className="brand-title">{t('app.name')}</h1>
          <LanguageToggle />
        </div>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  )
}

/** A link to choose a new password, by email (D87). The answer is the same whether the email has an account. */
export function ForgotPasswordPage() {
  const { t } = useTranslation()
  const action = useAction()
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (await action.run(() => http.post('/api/auth/password/forgot/', { email: email.trim() }))) setSent(true)
  }

  return (
    <Card title={t('password.forgotTitle')}>
      {sent ? (
        <p className="notice" role="status" data-testid="password-link-sent">
          {t('password.linkSent')}
        </p>
      ) : (
        <form onSubmit={submit} data-testid="password-forgot">
          <p className="muted">{t('password.forgotHint')}</p>
          <label className="field">
            <span>{t('login.email')}</span>
            <input type="email" dir="ltr" required value={email} data-testid="password-email" onChange={(e) => setEmail(e.target.value)} />
          </label>
          <ErrorMessage code={action.error} testId="password-error" />
          <button type="submit" className="primary" disabled={action.busy}>
            {t('password.sendLink')}
          </button>
        </form>
      )}
      <Link to="/login">{t('password.backToSignIn')}</Link>
    </Card>
  )
}

/** The password a person chooses from an invitation's or a reset's link (D87). */
export function SetPasswordPage() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const action = useAction()
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [done, setDone] = useState(false)
  const [mismatch, setMismatch] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setMismatch(password !== again)
    if (password !== again) return
    const body = { uid: params.get('uid') ?? '', token: params.get('token') ?? '', password }
    // The answer is empty (204): success is told by the run finishing without an error.
    const saved = await action.run(async () => {
      await http.post('/api/auth/password/set/', body)
      return true
    })
    if (saved) setDone(true)
  }

  return (
    <Card title={t('password.setTitle')}>
      {done ? (
        <p className="notice" role="status" data-testid="password-set">
          {t('password.setDone')}
        </p>
      ) : (
        <form onSubmit={submit} data-testid="password-choose">
          <p className="muted">{t('password.rules')}</p>
          <label className="field">
            <span>{t('password.new')}</span>
            <input type="password" dir="ltr" autoComplete="new-password" required value={password} data-testid="password-new" onChange={(e) => setPassword(e.target.value)} />
          </label>
          <label className="field">
            <span>{t('password.again')}</span>
            <input type="password" dir="ltr" autoComplete="new-password" required value={again} data-testid="password-again" onChange={(e) => setAgain(e.target.value)} />
          </label>
          {mismatch && (
            <p role="alert" className="error" data-testid="password-mismatch">
              {t('password.mismatch')}
            </p>
          )}
          <ErrorMessage code={action.error} testId="password-error" />
          <button type="submit" className="primary" disabled={action.busy}>
            {t('password.save')}
          </button>
        </form>
      )}
      <Link to="/login" data-testid="password-to-sign-in">
        {t('password.backToSignIn')}
      </Link>
    </Card>
  )
}
