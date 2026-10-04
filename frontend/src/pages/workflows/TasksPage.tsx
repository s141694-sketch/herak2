import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { http } from '../../api'
import { useAuth } from '../../auth'
import { ErrorMessage, Loading } from '../../components/ErrorMessage'
import { useAction, useResource } from '../../hooks/useResource'
import type { StageTask } from '../../types'
import { useAssignee } from './WorkflowsPage'

export function useDate() {
  const { i18n } = useTranslation()
  return (value: string | null | undefined) => (value ? new Date(value).toLocaleString(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }) : '')
}

/** One task: where it is, whose it is, when it is due; and taking it or giving it back. */
export function TaskSummary({ task, onChanged }: { task: StageTask; onChanged: () => void }) {
  const { t } = useTranslation()
  const action = useAction()
  const assignee = useAssignee()
  const date = useDate()
  const act = (path: 'claim' | 'release') => void action.run(() => http.post(`/api/tasks/${task.id}/${path}/`)).then((done) => done && onChanged())
  return (
    <div className="row task" data-testid="task" data-task={task.id}>
      <span className="badge">{t('workflow.stageOf', { stage: task.stage, count: task.stage_count })}</span>
      <strong>{task.stage_name}</strong>
      <span>{task.claimed_by ? t('workflow.takenBy', { name: task.claimed_by.full_name || task.claimed_by.email }) : assignee(task)}</span>
      <span className={task.overdue ? 'badge badge-returned' : 'muted'} data-testid="task-due">
        {task.overdue ? t('workflow.overdue', { date: date(task.due_at) }) : t('workflow.due', { date: date(task.due_at) })}
      </span>
      {task.permissions.can_claim && (
        <button type="button" className="secondary" disabled={action.busy} data-testid="task-claim" onClick={() => act('claim')}>
          {t('workflow.claim')}
        </button>
      )}
      {task.permissions.can_release && (
        <button type="button" className="link-button" disabled={action.busy} data-testid="task-release" onClick={() => act('release')}>
          {t('workflow.release')}
        </button>
      )}
      <ErrorMessage code={action.error} />
    </div>
  )
}

/** The reviewer's inbox (task 5.10): their tasks and their role's tasks nobody has taken; an admin may follow all. */
export function TasksPage() {
  const { t } = useTranslation()
  const { session } = useAuth()
  const [all, setAll] = useState(false)
  const tasks = useResource<StageTask[]>(all ? '/api/tasks/?scope=all' : '/api/tasks/')
  const isAdmin = session?.organization?.role === 'admin'

  return (
    <section className="card">
      <h1>{t('workflow.inbox')}</h1>
      {isAdmin && (
        <label className="inline">
          <input type="checkbox" checked={all} data-testid="tasks-all" onChange={(e) => setAll(e.target.checked)} />
          <span>{t('workflow.allOpen')}</span>
        </label>
      )}
      <ErrorMessage code={tasks.error} />
      {tasks.loading && !tasks.data && <Loading />}
      {tasks.data?.length === 0 && <p className="muted" data-testid="tasks-empty">{t('workflow.noTasks')}</p>}
      <ul className="plain" data-testid="task-list">
        {tasks.data?.map((task) => (
          <li key={task.id} className="panel">
            <p>
              <Link to={`/program-versions/${task.version.id}`} data-testid="task-open">
                {task.version.program.title} — {t('common.version', { number: task.version.number })}
              </Link>
            </p>
            <TaskSummary task={task} onChanged={tasks.reload} />
          </li>
        ))}
      </ul>
    </section>
  )
}
