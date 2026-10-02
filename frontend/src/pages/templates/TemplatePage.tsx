import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router'

import { http } from '../../api'
import { useAuth } from '../../auth'
import { ErrorMessage, Loading } from '../../components/ErrorMessage'
import { StatusBadge } from '../../components/StatusBadge'
import { useAction, useResource } from '../../hooks/useResource'
import type { Template, TemplateVersionDetail } from '../../types'
import { type LevelDraft, LevelsEditor } from './LevelsEditor'

export function TemplatePage() {
  const { t, i18n } = useTranslation()
  const { id } = useParams()
  const { session } = useAuth()
  const isAdmin = session?.organization?.role === 'admin'
  const template = useResource<Template>(`/api/structure-templates/${id}/`)
  const [selected, setSelected] = useState<number | null>(null)
  const versionId = selected ?? template.data?.versions[template.data.versions.length - 1]?.id ?? null
  const version = useResource<TemplateVersionDetail>(versionId ? `/api/template-versions/${versionId}/` : null)
  const [levels, setLevels] = useState<LevelDraft[]>([])
  const action = useAction()

  useEffect(() => {
    if (version.data) setLevels(version.data.levels.map(({ name_ar, name_en }) => ({ name_ar, name_en })))
  }, [version.data])

  const refresh = () => {
    template.reload()
    version.reload()
  }

  if (template.loading && !template.data) return <Loading />
  if (!template.data) return <ErrorMessage code={template.error} />
  const draft = version.data?.status === 'draft'

  return (
    <section className="card">
      <h1>{template.data.name}</h1>
      <div className="tabs" data-testid="template-versions">
        {template.data.versions.map((v) => (
          <button
            key={v.id}
            type="button"
            className={v.id === versionId ? 'tab active' : 'tab'}
            onClick={() => setSelected(v.id)}
          >
            {t('common.version', { number: v.number })} <StatusBadge status={v.status} />
          </button>
        ))}
      </div>
      <ErrorMessage code={version.error ?? action.error} />
      {version.data && (
        <>
          {draft && isAdmin ? (
            <>
              <LevelsEditor levels={levels} onChange={setLevels} />
              <div className="row">
                <button
                  type="button"
                  className="secondary"
                  disabled={action.busy}
                  data-testid="save-levels"
                  onClick={() => void action.run(() => http.put(`/api/template-versions/${versionId}/levels/`, levels)).then(refresh)}
                >
                  {t('templates.saveLevels')}
                </button>
                <button
                  type="button"
                  className="primary-inline"
                  disabled={action.busy}
                  data-testid="publish-template"
                  onClick={() => void action.run(() => http.post(`/api/template-versions/${versionId}/publish/`)).then(refresh)}
                >
                  {t('common.publish')}
                </button>
              </div>
            </>
          ) : (
            <ol className="levels" data-testid="template-levels">
              {version.data.levels.map((level) => (
                <li key={level.depth}>{i18n.language === 'ar' ? level.name_ar : level.name_en}</li>
              ))}
            </ol>
          )}
          {!draft && isAdmin && !template.data.versions.some((v) => v.status === 'draft') && (
            <div className="row">
              <p className="muted">{t('templates.noDraftHint')}</p>
              <button
                type="button"
                className="secondary"
                data-testid="new-template-version"
                onClick={() =>
                  void action.run(() => http.post(`/api/structure-templates/${id}/versions/`)).then((created) => {
                    if (created) {
                      setSelected(null)
                      refresh()
                    }
                  })
                }
              >
                {t('common.newVersion')}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
