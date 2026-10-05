import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { api, http, type SessionPayload } from '../api'
import { useAuth } from '../auth'
import { ErrorMessage } from '../components/ErrorMessage'
import { useAction } from '../hooks/useResource'

function CodeInput({ value, onChange, testId }: { value: string; onChange: (code: string) => void; testId: string }) {
  const { t } = useTranslation()
  return (
    <label className="field">
      <span>{t('login.code')}</span>
      <input
        inputMode="numeric"
        autoComplete="one-time-code"
        dir="ltr"
        maxLength={6}
        required
        value={value}
        data-testid={testId}
        onChange={(event) => onChange(event.target.value.replace(/\D/g, ''))}
      />
    </label>
  )
}

/** A person's own second factor (spec 7.1, task 6.7): set it up with an authenticator app, or turn it off. It
 * works in every organization of theirs; signing in through an organization's provider does not use it. */
export function AccountSecurityPage() {
  const { t } = useTranslation()
  const { session, setSession } = useAuth()
  const action = useAction()
  const [enrolment, setEnrolment] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [code, setCode] = useState('')
  const [done, setDone] = useState<string | null>(null)
  if (!session) return null
  const enabled = session.user.mfa_enabled

  const start = async () => {
    setDone(null)
    const started = await action.run(() => http.post<{ secret: string; otpauth_uri: string }>('/api/auth/mfa/enrol/'))
    if (started) setEnrolment(started)
  }
  const confirm = async (event: FormEvent) => {
    event.preventDefault()
    const payload = await action.run(() => http.post<SessionPayload>('/api/auth/mfa/confirm/', { code }))
    if (payload) {
      setSession(payload)
      setEnrolment(null)
      setCode('')
      setDone('mfa.turnedOn')
    }
  }
  const turnOff = async (event: FormEvent) => {
    event.preventDefault()
    if ((await action.run(() => http.post('/api/auth/mfa/disable/', { code }))) === undefined) return
    setCode('')
    setSession(await api.me())
    setDone('mfa.turnedOff')
  }

  return (
    <section className="card" data-testid="account-security">
      <h1>{t('mfa.title')}</h1>
      <p className="muted">{t('mfa.intro')}</p>
      <p data-testid="mfa-status" data-enabled={enabled}>
        {enabled ? t('mfa.statusOn') : t('mfa.statusOff')}
      </p>
      {done && (
        <p className="notice" role="status">
          {t(done)}
        </p>
      )}
      <ErrorMessage code={action.error} testId="mfa-error" />

      {!enabled && !enrolment && (
        <button type="button" className="primary-inline" data-testid="mfa-start" disabled={action.busy} onClick={() => void start()}>
          {t('mfa.start')}
        </button>
      )}
      {enrolment && (
        <form className="stack" onSubmit={confirm}>
          <ol>
            <li>{t('mfa.stepApp')}</li>
            <li>
              {t('mfa.stepKey')}
              <p>
                <code dir="ltr" data-testid="mfa-secret">
                  {enrolment.secret}
                </code>
              </p>
              <p className="muted small">
                {t('mfa.stepLink')}{' '}
                <a href={enrolment.otpauth_uri}>{t('mfa.openInApp')}</a>
              </p>
            </li>
            <li>{t('mfa.stepCode')}</li>
          </ol>
          <CodeInput value={code} onChange={setCode} testId="mfa-confirm-code" />
          <button type="submit" className="primary-inline" disabled={action.busy || code.length !== 6} data-testid="mfa-confirm">
            {t('mfa.confirm')}
          </button>
        </form>
      )}
      {enabled && (
        <form className="stack" onSubmit={turnOff}>
          <h2>{t('mfa.turnOff')}</h2>
          <CodeInput value={code} onChange={setCode} testId="mfa-disable-code" />
          <button type="submit" className="secondary" disabled={action.busy || code.length !== 6} data-testid="mfa-disable">
            {t('mfa.turnOff')}
          </button>
        </form>
      )}
      <p>
        <Link to="/">{t('mfa.back')}</Link>
      </p>
    </section>
  )
}
