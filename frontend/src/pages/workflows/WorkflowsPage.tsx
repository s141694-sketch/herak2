import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { http } from '../../api'
import { useAuth } from '../../auth'
import { ErrorMessage, Loading } from '../../components/ErrorMessage'
import { useAction, useResource } from '../../hooks/useResource'
import type { Member, StageRole, WorkflowStage, WorkflowTemplate } from '../../types'

const ROLES: StageRole[] = ['reviewer', 'approver', 'admin']

interface StageDraft {
  name: string
  who: 'role' | 'user'
  assignee_role: StageRole
  assignee_user: number | ''
  due_work_days: number
  resubmit: 'same_stage' | 'restart'
}

const emptyStage = (): StageDraft => ({ name: '', who: 'role', assignee_role: 'reviewer', assignee_user: '', due_work_days: 3, resubmit: 'same_stage' })

const draftOf = (stage: WorkflowStage): StageDraft => ({
  name: stage.name,
  who: stage.assignee_user ? 'user' : 'role',
  assignee_role: (stage.assignee_role || 'reviewer') as StageRole,
  assignee_user: stage.assignee_user?.id ?? '',
  due_work_days: stage.due_work_days,
  resubmit: stage.resubmit,
})

const bodyOf = (stage: StageDraft) => ({
  name: stage.name,
  due_work_days: stage.due_work_days,
  resubmit: stage.resubmit,
  ...(stage.who === 'user' ? { assignee_user: stage.assignee_user === '' ? null : stage.assignee_user } : { assignee_role: stage.assignee_role }),
})

/** Who is responsible for a stage, as people read it. */
export function useAssignee() {
  const { t } = useTranslation()
  return (stage: Pick<WorkflowStage, 'assignee_user' | 'assignee_role'>) =>
    stage.assignee_user ? stage.assignee_user.full_name || stage.assignee_user.email : t('workflow.anyRole', { role: t(`roles.${stage.assignee_role}`) })
}

function StagesEditor({
  stages,
  members,
  current,
  onChange,
}: {
  stages: StageDraft[]
  members: Member[]
  /** The people the template names now, shown even if their role no longer lets them review. */
  current: WorkflowStage[]
  onChange: (stages: StageDraft[]) => void
}) {
  const { t } = useTranslation()
  const set = (index: number, change: Partial<StageDraft>) => onChange(stages.map((stage, i) => (i === index ? { ...stage, ...change } : stage)))
  const deciders = members.filter((m) => ROLES.includes(m.role as StageRole))
  const named = current
    .map((stage) => stage.assignee_user)
    .filter((user): user is NonNullable<typeof user> => user !== null && !deciders.some((m) => m.user.id === user.id))
  return (
    <ol className="stages" data-testid="stages-editor">
      {stages.map((stage, index) => (
        <li key={index} className="row" data-testid="stage-draft">
          <input
            required
            maxLength={200}
            aria-label={t('workflow.stageName')}
            placeholder={t('workflow.stageName')}
            value={stage.name}
            data-testid="stage-name"
            onChange={(e) => set(index, { name: e.target.value })}
          />
          <select aria-label={t('workflow.who')} value={stage.who} data-testid="stage-who" onChange={(e) => set(index, { who: e.target.value as StageDraft['who'] })}>
            <option value="role">{t('workflow.byRole')}</option>
            <option value="user">{t('workflow.byPerson')}</option>
          </select>
          {stage.who === 'role' ? (
            <select aria-label={t('workflow.role')} value={stage.assignee_role} data-testid="stage-role" onChange={(e) => set(index, { assignee_role: e.target.value as StageRole })}>
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {t(`roles.${role}`)}
                </option>
              ))}
            </select>
          ) : (
            <select
              required
              aria-label={t('workflow.person')}
              value={stage.assignee_user}
              data-testid="stage-user"
              onChange={(e) => set(index, { assignee_user: e.target.value === '' ? '' : Number(e.target.value) })}
            >
              <option value="">{t('workflow.choosePerson')}</option>
              {deciders.map((m) => (
                <option key={m.user.id} value={m.user.id}>
                  {t('workflow.personWithRole', { name: m.user.full_name || m.user.email, role: t(`roles.${m.role}`) })}
                </option>
              ))}
              {named.map((user) => (
                <option key={user.id} value={user.id}>
                  {t('workflow.personCannotReview', { name: user.full_name || user.email })}
                </option>
              ))}
            </select>
          )}
          <label className="inline">
            <span>{t('workflow.dueDays')}</span>
            <input
              type="number"
              min={0}
              max={365}
              required
              value={stage.due_work_days}
              data-testid="stage-days"
              onChange={(e) => set(index, { due_work_days: Number(e.target.value) })}
            />
          </label>
          <select aria-label={t('workflow.resubmit')} value={stage.resubmit} data-testid="stage-resubmit" onChange={(e) => set(index, { resubmit: e.target.value as StageDraft['resubmit'] })}>
            <option value="same_stage">{t('workflow.resubmitSame')}</option>
            <option value="restart">{t('workflow.resubmitRestart')}</option>
          </select>
          {stages.length > 1 && (
            <button type="button" className="link-button" onClick={() => onChange(stages.filter((_, i) => i !== index))}>
              {t('programs.remove')}
            </button>
          )}
        </li>
      ))}
      <li>
        <button type="button" className="secondary" data-testid="add-stage" onClick={() => onChange([...stages, emptyStage()])}>
          {t('workflow.addStage')}
        </button>
      </li>
    </ol>
  )
}

function TemplateForm({
  template,
  members,
  onSaved,
  onCancel,
}: {
  template: WorkflowTemplate | null
  members: Member[]
  onSaved: () => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const action = useAction()
  const [name, setName] = useState(template?.name ?? '')
  const [isDefault, setIsDefault] = useState(template?.is_default ?? false)
  const [stages, setStages] = useState<StageDraft[]>(template ? template.stages.map(draftOf) : [emptyStage()])

  async function save(event: FormEvent) {
    event.preventDefault()
    const body = { name, is_default: isDefault, stages: stages.map(bodyOf) }
    const saved = await action.run(() => (template ? http.put(`/api/workflow-templates/${template.id}/`, body) : http.post('/api/workflow-templates/', body)))
    if (saved) onSaved()
  }

  return (
    <form className="stack panel" onSubmit={save} data-testid="workflow-form">
      <h2>{template ? t('workflow.edit', { name: template.name }) : t('workflow.new')}</h2>
      <label className="field">
        <span>{t('common.name')}</span>
        <input required maxLength={200} value={name} data-testid="workflow-name" onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="inline">
        <input type="checkbox" checked={isDefault} data-testid="workflow-default" onChange={(e) => setIsDefault(e.target.checked)} />
        <span>{t('workflow.isDefault')}</span>
      </label>
      <h3>{t('workflow.stages')}</h3>
      <StagesEditor stages={stages} members={members} current={template?.stages ?? []} onChange={setStages} />
      <p className="muted">{t('workflow.snapshotNote')}</p>
      <ErrorMessage code={action.error} />
      <div className="row">
        <button type="submit" className="primary-inline" disabled={action.busy} data-testid="workflow-save">
          {t('common.save')}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          {t('common.cancel')}
        </button>
      </div>
    </form>
  )
}

/** Approval workflows (task 5.10): the organization's templates; admins create and edit them. */
export function WorkflowsPage() {
  const { t } = useTranslation()
  const { session } = useAuth()
  const templates = useResource<WorkflowTemplate[]>('/api/workflow-templates/')
  const members = useResource<Member[]>('/api/organizations/current/members/')
  const action = useAction()
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const isAdmin = session?.organization?.role === 'admin'
  const assignee = useAssignee()

  const saved = () => {
    setEditing(null)
    templates.reload()
  }

  return (
    <section className="card">
      <h1>{t('workflow.title')}</h1>
      <p className="muted">{t('workflow.intro')}</p>
      <ErrorMessage code={templates.error ?? action.error} />
      {templates.loading && !templates.data && <Loading />}
      {templates.data?.length === 0 && <p className="notice">{t('workflow.none')}</p>}
      <ul className="plain" data-testid="workflow-list">
        {templates.data?.map((template) => (
          <li key={template.id} className="panel" data-testid="workflow-item">
            <h2>
              <span dir="auto">{template.name}</span> {template.is_default && <span className="badge badge-approved">{t('workflow.default')}</span>}
            </h2>
            <ol>
              {template.stages.map((stage) => (
                <li key={stage.order}>
                  {t('workflow.stageLine', {
                    name: stage.name,
                    who: assignee(stage),
                    days: stage.due_work_days,
                    resubmit: stage.resubmit === 'restart' ? t('workflow.resubmitRestart') : t('workflow.resubmitSame'),
                  })}
                </li>
              ))}
            </ol>
            {isAdmin && (
              <div className="row">
                <button type="button" className="secondary" data-testid="workflow-edit" onClick={() => setEditing(template.id)}>
                  {t('common.edit')}
                </button>
                <button
                  type="button"
                  className="link-button"
                  data-testid="workflow-delete"
                  onClick={() => {
                    const question = template.is_default ? t('workflow.confirmDeleteDefault', { name: template.name }) : t('workflow.confirmDelete', { name: template.name })
                    if (window.confirm(question)) void action.run(() => http.del(`/api/workflow-templates/${template.id}/`)).then(templates.reload)
                  }}
                >
                  {t('common.delete')}
                </button>
              </div>
            )}
            {editing === template.id && <TemplateForm template={template} members={members.data ?? []} onSaved={saved} onCancel={() => setEditing(null)} />}
          </li>
        ))}
      </ul>
      {isAdmin && editing !== 'new' && (
        <button type="button" className="primary-inline" data-testid="workflow-new" onClick={() => setEditing('new')}>
          {t('workflow.new')}
        </button>
      )}
      {editing === 'new' && <TemplateForm template={null} members={members.data ?? []} onSaved={saved} onCancel={() => setEditing(null)} />}
    </section>
  )
}
