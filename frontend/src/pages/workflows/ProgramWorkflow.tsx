import { useTranslation } from 'react-i18next'

import { http } from '../../api'
import { ErrorMessage } from '../../components/ErrorMessage'
import { useAction, useResource } from '../../hooks/useResource'
import type { WorkflowTemplate } from '../../types'

/** The approval workflow a program follows: its own choice while it has a draft, or the organization's default. */
export function ProgramWorkflow({ programId, canChoose }: { programId: number; canChoose: boolean }) {
  const { t } = useTranslation()
  const current = useResource<{ chosen: number | null; template: WorkflowTemplate | null }>(`/api/programs/${programId}/workflow/`)
  const templates = useResource<WorkflowTemplate[]>(canChoose ? '/api/workflow-templates/' : null)
  const action = useAction()
  if (!current.data) return <ErrorMessage code={current.error} />
  const { chosen, template } = current.data

  return (
    <div data-testid="program-workflow">
      <h2>{t('workflow.programWorkflow')}</h2>
      {template ? (
        <p>
          <strong>{template.name}</strong> — {template.stages.map((s) => s.name).join(' ← ')}
          {chosen === null && <span className="muted"> ({t('workflow.default')})</span>}
        </p>
      ) : (
        <p className="notice">{t('workflow.noneForProgram')}</p>
      )}
      {canChoose && templates.data && templates.data.length > 1 && (
        <select
          aria-label={t('workflow.choose')}
          value={chosen ?? ''}
          data-testid="program-workflow-choice"
          onChange={(e) =>
            void action
              .run(() => http.put(`/api/programs/${programId}/workflow/`, { template: e.target.value === '' ? null : Number(e.target.value) }))
              .then(current.reload)
          }
        >
          <option value="">{t('workflow.useDefault')}</option>
          {templates.data.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
        </select>
      )}
      <ErrorMessage code={action.error} />
    </div>
  )
}
