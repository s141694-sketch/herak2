import { useTranslation } from 'react-i18next'

import type { Level } from '../../types'

export type LevelDraft = Pick<Level, 'name_ar' | 'name_en'>
export const MAX_LEVELS = 5

export function LevelsEditor({ levels, onChange }: { levels: LevelDraft[]; onChange: (levels: LevelDraft[]) => void }) {
  const { t } = useTranslation()
  const update = (index: number, field: keyof LevelDraft, value: string) =>
    onChange(levels.map((level, i) => (i === index ? { ...level, [field]: value } : level)))

  return (
    <div className="levels-editor">
      {levels.map((level, index) => (
        <div className="level-row" key={index} data-testid={`level-row-${index}`}>
          <span className="muted">{t('templates.levelNumber', { number: index + 1 })}</span>
          <input
            aria-label={t('templates.levelAr')}
            placeholder={t('templates.levelAr')}
            dir="rtl"
            value={level.name_ar}
            data-testid={`level-ar-${index}`}
            onChange={(event) => update(index, 'name_ar', event.target.value)}
          />
          <input
            aria-label={t('templates.levelEn')}
            placeholder={t('templates.levelEn')}
            dir="ltr"
            value={level.name_en}
            data-testid={`level-en-${index}`}
            onChange={(event) => update(index, 'name_en', event.target.value)}
          />
          <button type="button" className="secondary" onClick={() => onChange(levels.filter((_, i) => i !== index))}>
            {t('templates.removeLevel')}
          </button>
        </div>
      ))}
      {levels.length < MAX_LEVELS ? (
        <button
          type="button"
          className="secondary"
          data-testid="add-level"
          onClick={() => onChange([...levels, { name_ar: '', name_en: '' }])}
        >
          {t('templates.addLevel')}
        </button>
      ) : (
        <p className="muted">{t('templates.maxLevels')}</p>
      )}
    </div>
  )
}
