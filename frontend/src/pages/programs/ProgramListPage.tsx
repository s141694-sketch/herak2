import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'

import { http } from '../../api'
import { useAuth } from '../../auth'
import { ErrorMessage, Loading } from '../../components/ErrorMessage'
import { StatusBadge } from '../../components/StatusBadge'
import { useAction, useResource } from '../../hooks/useResource'
import type { Framework, FrameworkVersionDetail, Program, Template } from '../../types'

export function ProgramListPage() {
  const { t } = useTranslation()
  const { session } = useAuth()
  const navigate = useNavigate()
  const programs = useResource<Program[]>('/api/programs/')
  const templates = useResource<Template[]>('/api/structure-templates/')
  const frameworks = useResource<Framework[]>('/api/competency-frameworks/')
  const action = useAction()
  const [title, setTitle] = useState('')
  const [targetRole, setTargetRole] = useState('')
  const [templateVersion, setTemplateVersion] = useState('')
  const [frameworkVersion, setFrameworkVersion] = useState('')
  const [targets, setTargets] = useState<number[]>([])
  const framework = useResource<FrameworkVersionDetail>(frameworkVersion ? `/api/framework-versions/${frameworkVersion}/` : null)
  const canCreate = session?.organization?.role === 'admin' || session?.organization?.role === 'author'

  async function create(event: FormEvent) {
    event.preventDefault()
    const created = await action.run(() =>
      http.post<Program>('/api/programs/', {
        title,
        target_role: targetRole,
        template_version: Number(templateVersion),
        framework_version: Number(frameworkVersion),
        targets,
      }),
    )
    if (created) navigate(`/programs/${created.id}`)
  }

  const publishedTemplates = (templates.data ?? []).flatMap((tpl) =>
    tpl.versions.filter((v) => v.status === 'published').map((v) => ({ id: v.id, label: t('programs.templateOption', { name: tpl.name, number: v.number }) })),
  )
  const publishedFrameworks = (frameworks.data ?? []).flatMap((fw) =>
    fw.versions.filter((v) => v.status === 'published').map((v) => ({ id: v.id, label: t('programs.templateOption', { name: fw.name, number: v.number }) })),
  )

  return (
    <section className="card">
      <h1>{t('programs.title')}</h1>
      <ErrorMessage code={programs.error} />
      {programs.loading && <Loading />}
      <table className="table" data-testid="program-list">
        <tbody>
          {programs.data?.map((program) => (
            <tr key={program.id}>
              <td>
                <Link to={`/programs/${program.id}`}>{program.title}</Link>
              </td>
              <td>{program.target_role}</td>
              <td>
                <StatusBadge status={program.status} />
              </td>
              <td>{program.owner.full_name || program.owner.email}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {programs.data?.length === 0 && <p className="muted">{t('common.empty')}</p>}

      {canCreate && (
        <form className="stack" onSubmit={create} data-testid="new-program">
          <h2>{t('programs.new')}</h2>
          <label className="field">
            <span>{t('programs.programTitle')}</span>
            <input required value={title} data-testid="program-title" onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="field">
            <span>{t('programs.targetRole')}</span>
            <input value={targetRole} data-testid="program-role" onChange={(e) => setTargetRole(e.target.value)} />
          </label>
          <label className="field">
            <span>{t('programs.template')}</span>
            <select required value={templateVersion} data-testid="program-template" onChange={(e) => setTemplateVersion(e.target.value)}>
              <option value="">{t('programs.chooseTemplate')}</option>
              {publishedTemplates.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>{t('programs.framework')}</span>
            <select
              required
              value={frameworkVersion}
              data-testid="program-framework"
              onChange={(e) => {
                setFrameworkVersion(e.target.value)
                setTargets([])
              }}
            >
              <option value="">{t('programs.chooseFramework')}</option>
              {publishedFrameworks.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          {framework.data && (
            <fieldset className="checks" data-testid="program-targets">
              <legend>{t('programs.targets')}</legend>
              {framework.data.competencies.map((c) => (
                <label key={c.id}>
                  <input
                    type="checkbox"
                    checked={targets.includes(c.id)}
                    onChange={(e) => setTargets(e.target.checked ? [...targets, c.id] : targets.filter((i) => i !== c.id))}
                  />
                  <span dir="ltr">{c.code}</span> {c.title}
                </label>
              ))}
            </fieldset>
          )}
          <ErrorMessage code={action.error} />
          <button type="submit" className="primary-inline" disabled={action.busy} data-testid="create-program">
            {t('common.create')}
          </button>
        </form>
      )}
    </section>
  )
}
