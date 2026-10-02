import { useTranslation } from 'react-i18next'

export function LanguageToggle() {
  const { t, i18n } = useTranslation()
  const next = i18n.language === 'ar' ? 'en' : 'ar'
  return (
    <button
      type="button"
      className="link-button"
      data-testid="language-toggle"
      lang={next}
      aria-label={t('language.label')}
      onClick={() => void i18n.changeLanguage(next)}
    >
      {t('language.switchTo')}
    </button>
  )
}
