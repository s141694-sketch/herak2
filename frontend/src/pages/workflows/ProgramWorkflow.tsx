import { useTranslation } from 'react-i18next'

import { http } from '../../api'
import { ErrorMessage } from '../../components/ErrorMessage'
import { useAction, useResource } from '../../hooks/useResource'
import type { WorkflowTemplate } from '../../types'

interface ProgramWorkflowBody {
  chosen: number | null
  template: WorkflowTemplate | null
  /** The returned version the program's draft answers: its resubmission follows that review's stages (D54). */
  resubmission_of: number | null
}

/** The approval workflow a program follows: its own choice while it has a draft, or the organization's default. */
export function ProgramWorkflow({ programId, canChoose }: { programId: number; canChoose: boolean }) {
  const { t } = useTranslation()
  const current = useResource<ProgramWorkflowBody>(`/api/programs/${programId}/workflow/`)
  const templates = useResource<WorkflowTemplate[]>(canChoose ? '/api/workflow-templates/' : null)
  const action = useAction()
  if (!current.data) return <ErrorMessage code={current.error} />
  const { chosen, template, resubmission_of: resubmission } = current.data

  return (
    <div data-testid="program-workflow">
      <h2>{t('workflow.programWorkflow')}</h2>
      {template ? (
        <>
          <p>
            <strong dir="auto">{template.name}</strong>
            {chosen === null && resubmission === null && <span className="muted"> ({t('workflow.default')})</span>}
          </p>
          <ol className="stages-progress">
            {template.stages.map((stage) => (
              <li key={stage.order} dir="auto">
                {stage.name}
              </li>
            ))}
          </ol>
        </>
      ) : (
        <p className="notice">{t('workflow.noneForProgram')}</p>
      )}
      {resubmission !== null ? (
        <p className="muted" data-testid="program-workflow-fixed">
          {t('workflow.followsReturn', { number: resubmission })}
        </p>
      ) : (
        canChoose &&
        templates.data &&
        templates.data.length > 0 && (
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
        )
      )}
      <ErrorMessage code={action.error} />
    </div>
  )
}
