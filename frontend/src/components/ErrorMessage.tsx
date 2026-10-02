import { useTranslation } from 'react-i18next'

export function ErrorMessage({ code, testId }: { code: string | null | undefined; testId?: string }) {
  const { t } = useTranslation()
  if (!code) return null
  return (
    <p role="alert" className="error" data-testid={testId ?? 'error'}>
      {t(`errors.${code}`, { defaultValue: t('errors.unknown') })}
    </p>
  )
}

export function Loading() {
  const { t } = useTranslation()
  return <p className="muted">{t('common.loading')}</p>
}
