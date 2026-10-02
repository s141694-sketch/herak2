import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import ar from './ar.json'
import en from './en.json'

export const LANGUAGES = ['ar', 'en'] as const
export type Language = (typeof LANGUAGES)[number]

const STORAGE_KEY = 'harak.language'

export function directionOf(language: string): 'rtl' | 'ltr' {
  return language === 'ar' ? 'rtl' : 'ltr'
}

function storedLanguage(): Language {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'en' ? 'en' : 'ar'
  } catch {
    return 'ar'
  }
}

/** Keeps <html lang dir> in step with the active language so the whole layout flips. */
function applyToDocument(language: string) {
  document.documentElement.lang = language
  document.documentElement.dir = directionOf(language)
  try {
    localStorage.setItem(STORAGE_KEY, language)
  } catch {
    // Storage can be unavailable (private mode); the language still applies for this page.
  }
}

void i18n.use(initReactI18next).init({
  resources: { ar: { translation: ar }, en: { translation: en } },
  lng: typeof window === 'undefined' ? 'ar' : storedLanguage(),
  fallbackLng: 'ar',
  interpolation: { escapeValue: false },
  returnNull: false,
})

if (typeof document !== 'undefined') {
  applyToDocument(i18n.language)
  i18n.on('languageChanged', applyToDocument)
}

export default i18n
