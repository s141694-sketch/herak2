import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { http } from '../api'
import { useAuth } from '../auth'
import { ErrorMessage, Loading } from '../components/ErrorMessage'
import { useAction, useResource } from '../hooks/useResource'

interface Identity {
  primary_color: string
  logo: { id: number; name: string } | null
}

/** The organization's identity (spec 4.1), which its exported Word and PDF files carry (task 7.3). */
export function IdentitySettingsPage() {
  const { t } = useTranslation()
  const { session } = useAuth()
  const identity = useResource<Identity>('/api/organizations/current/identity/')
  const action = useAction()
  const [color, setColor] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  if (!session?.organization) return <Loading />
  if (session.organization.role !== 'admin') return <ErrorMessage code="permission_denied" />
  if (!identity.data) return <ErrorMessage code={identity.error} />
  const current = identity.data
  const shown = color ?? (current.primary_color || '#1F4E79')

  const saveColor = async (event: FormEvent) => {
    event.preventDefault()
    setSaved(false)
    if (await action.run(() => http.patch('/api/organizations/current/identity/', { primary_color: shown }))) {
      identity.reload()
      setSaved(true)
    }
  }
  const uploadLogo = async (file: File) => {
    setSaved(false)
    if (await action.run(() => http.upload('/api/organizations/current/identity/logo/', file))) identity.reload()
  }
  const removeLogo = async () => {
    if (await action.run(() => http.del('/api/organizations/current/identity/logo/'))) identity.reload()
  }

  return (
    <section className="card" data-testid="identity-settings">
      <h1>{t('identity.title')}</h1>
      <p className="muted">{t('identity.intro')}</p>
      <section className="panel">
        <h2>{t('identity.logo')}</h2>
        {current.logo ? (
          <div className="row">
            <img src={`/api/files/${current.logo.id}/download/`} alt={t('identity.logoAlt')} className="logo-preview" data-testid="identity-logo" />
            <button type="button" className="link-button" disabled={action.busy} onClick={() => void removeLogo()}>
              {t('identity.removeLogo')}
            </button>
          </div>
        ) : (
          <p className="muted">{t('identity.noLogo')}</p>
        )}
        <label className="field">
          <span>{t('identity.chooseLogo')}</span>
          <input
            type="file"
            accept="image/png,image/jpeg"
            disabled={action.busy}
            data-testid="identity-logo-file"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void uploadLogo(file)
            }}
          />
        </label>
        <p className="muted small">{t('identity.logoHint')}</p>
      </section>
      <form className="panel" onSubmit={saveColor}>
        <h2>{t('identity.color')}</h2>
        <label className="inline">
          <input type="color" value={shown} data-testid="identity-color" onChange={(e) => setColor(e.target.value)} />
          <span dir="ltr">{shown.toUpperCase()}</span>
        </label>
        <p className="muted small">{t('identity.colorHint')}</p>
        <button type="submit" className="secondary" disabled={action.busy} data-testid="identity-color-save">
          {t('common.save')}
        </button>
      </form>
      {saved && (
        <p className="notice" role="status">
          {t('identity.saved')}
        </p>
      )}
      <ErrorMessage code={action.error} testId="identity-error" />
    </section>
  )
}
