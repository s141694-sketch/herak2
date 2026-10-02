import { useTranslation } from 'react-i18next'

export function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation()
  return (
    <span className={`badge badge-${status}`} data-status={status}>
      {t(`status.${status}`)}
    </span>
  )
}
