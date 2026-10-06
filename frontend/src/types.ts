/** Shapes returned by the Django API for phase 2 screens. */

export type VersionStatus =
  | 'draft'
  | 'submitted'
  | 'in_stage'
  | 'approved'
  | 'exported'
  | 'returned'
  | 'withdrawn'
  | 'cancelled'

export interface Competency {
  id: number
  competency_key: string
  code: string
  title: string
  description: string
  level: string
  requirement: 'required' | 'optional'
  order: number
}

export interface FrameworkVersionSummary {
  id: number
  number: number
  status: 'draft' | 'published'
  published_at: string | null
  competency_count: number
}

export interface Framework {
  id: number
  name: string
  description: string
  versions: FrameworkVersionSummary[]
}

export interface FrameworkVersionDetail {
  id: number
  framework: { id: number; name: string }
  number: number
  status: 'draft' | 'published'
  competencies: Competency[]
}

export interface ImportRow {
  row: number
  values: Record<'code' | 'title' | 'description' | 'level' | 'requirement', string>
  errors: string[]
  action: 'create' | 'update' | 'unchanged' | 'error'
}

export interface CompetencyImport {
  id: number
  file_name: string
  status: 'previewed' | 'applied'
  summary: { create: number; update: number; unchanged: number; errors: number }
  rows: ImportRow[]
}

export interface Level {
  depth: number
  name_ar: string
  name_en: string
}

export interface TemplateVersionSummary {
  id: number
  number: number
  status: 'draft' | 'published'
  level_count: number
}

export interface Template {
  id: number
  name: string
  versions: TemplateVersionSummary[]
}

export interface TemplateVersionDetail {
  id: number
  template: { id: number; name: string }
  number: number
  status: 'draft' | 'published'
  levels: Level[]
}

export interface Permissions {
  /** The caller may change this content now (a collaborator on an editable version). */
  edit: boolean
  manage: boolean
  /** The caller is a collaborator, whatever the version's state. */
  collaborate: boolean
}

export interface ProgramVersionSummary {
  id: number
  number: number
  status: VersionStatus
  current_stage: number | null
}

export interface Program {
  id: number
  title: string
  target_role: string
  status: 'draft' | 'in_review' | 'approved' | 'archived'
  owner: { id: number; email: string; full_name: string }
  template_version: number
  versions: ProgramVersionSummary[]
  permissions: Permissions
}

export interface Collaborator {
  id: number
  user: { id: number; email: string; full_name: string }
}

export interface ProgramVersionDetail {
  id: number
  permissions: Permissions
  live: { is_live: boolean; materialized_at: string | null; last_error: string | null; last_error_code: string | null; issues: unknown[] }
  program: { id: number; title: string; owner_id: number }
  number: number
  status: VersionStatus
  source_version: number | null
  template: { id: number; name: string; number: number; levels: Level[] }
  framework: { id: number; name: string; number: number }
  targets: Array<{ id: number; code: string; title: string; competency_key: string }>
}

export interface TreeNode {
  id: number
  node_key: string
  parent: number | null
  level: number
  order: number
  title: string
  deleted: boolean
}

export type BlockType = 'objective' | 'content' | 'activity' | 'assessment' | 'reference'
export const BLOCK_TYPES: BlockType[] = ['objective', 'content', 'activity', 'assessment', 'reference']

export interface TreeBlock {
  id: number
  block_key: string
  node: number
  type: BlockType
  content: Record<string, unknown>
  order: number
  deleted: boolean
}

export interface AlignmentLink {
  id: number
  kind: 'objective_competency' | 'assessment_objective' | 'objective_parent'
  source: number
  target_block: number | null
  target_competency: number | null
  target_competency_code: string | null
}

export interface Tree {
  nodes: TreeNode[]
  blocks: TreeBlock[]
}

export type Change = 'added' | 'removed' | 'modified' | 'moved' | 'unchanged'

export interface DiffEntry {
  change: Change
  fields: string[]
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
}

export interface Diff {
  from: { id: number; number: number }
  to: { id: number; number: number }
  nodes: Array<DiffEntry & { node_key: string }>
  blocks: Array<DiffEntry & { block_key: string; text_before: string | null; text_after: string | null }>
  links: { added: Array<{ kind: string; source_key: string; competency_code: string | null }>; removed: Array<{ kind: string; source_key: string; competency_code: string | null }> }
  targets: { added: Array<{ code: string; title: string }>; removed: Array<{ code: string; title: string }> }
  summary: { nodes: Record<Change, number>; blocks: Record<Change, number> }
}

export interface CommentReply {
  id: number
  author: { id: number; email: string; full_name: string }
  body: string
  created_at: string
}

export interface ProgramComment {
  id: number
  version: number
  version_number: number
  block_key: string | null
  node_key: string | null
  anchor: { start: string; end: string } | null
  quoted: string
  body: string
  category: 'must_fix' | 'suggestion'
  status: 'open' | 'resolved'
  author: { id: number; email: string; full_name: string }
  created_at: string
  resolved_by: { id: number; email: string; full_name: string } | null
  replies: CommentReply[]
}

export type SuggestionStatus = 'pending' | 'ready' | 'rejected' | 'failed' | 'accepted' | 'dismissed'

export interface OutlineResult {
  nodes: Array<{ ref: string; parent: string; title: string }>
  objectives: Array<{ node: string; competency: string; competency_key: string; text: string }>
  dropped: { nodes: number; objectives: number }
  confidence: 'high' | 'medium' | 'low'
  explanation: string
}

export interface ImportResult {
  source: 'rules' | 'ai'
  nodes: Array<{ ref: string; parent: string; title: string }>
  blocks: Array<{ node: string; type: BlockType; text: string }>
  unplaced: string[]
  warnings: string[]
  confidence?: 'high' | 'medium' | 'low'
  explanation?: string
}

export interface RewriteResult {
  objective: string
  confidence: 'high' | 'medium' | 'low'
  explanation: string
}

/** An AI suggestion an author asked for (task 4.8); `result` only when it may be shown. */
export interface Suggestion {
  id: number
  version: number
  kind: 'rewrite' | 'outline' | 'import'
  subject: string
  status: SuggestionStatus
  reason: string
  original: string | null
  result: RewriteResult | OutlineResult | ImportResult | null
  requested_by: { id: number } | null
  model: string
  prompt_version: string
  created_at: string
  decided_at: string | null
  decision_reason: string
}

export type Severity = 'critical' | 'warning' | 'info'

export interface BloomReading {
  domain: 'cognitive' | 'affective' | 'psychomotor' | null
  level_id: number
  level: string
  verb?: string
}

export interface Finding {
  id: number
  /** The same across runs, which recreate findings with new ids. */
  key: string
  kind: string
  severity: Severity
  source: 'rule' | 'ai'
  confidence: 'high' | 'medium' | 'low'
  node_key: string | null
  block_key: string | null
  competency: { id: number; key: string; code: string; title: string } | null
  params: Record<string, unknown>
  explanation: string
  dismissal: { reason: string; at: string; by: { id: number; name: string } | null } | null
}

/** A version's quality report (spec 4.4): rules always, AI where rules cannot decide. */
export interface QualityReport {
  id: number
  version: number
  status: 'running' | 'complete' | 'partial_rules_only' | 'failed'
  last_run: 'light' | 'full'
  counts: Record<Severity, number>
  finished_at: string | null
  error: string
  findings: Finding[]
  rollup: Record<string, Record<Severity, number>>
}

/** Approval workflows (phase 5). */
export type StageRole = 'reviewer' | 'approver' | 'admin'
export interface UserRef {
  id: number
  email: string
  full_name: string
}

export interface WorkflowStage {
  order: number
  name: string
  assignee_user: UserRef | null
  assignee_role: StageRole | ''
  due_work_days: number
  resubmit: 'same_stage' | 'restart'
}

export interface WorkflowTemplate {
  id: number
  name: string
  is_default: boolean
  stages: WorkflowStage[]
  created_at: string
  updated_at: string
}

export interface StageTask {
  id: number
  stage: number
  stage_name: string
  stage_count: number
  assignee_user: UserRef | null
  assignee_role: StageRole | ''
  claimed_by: UserRef | null
  claimed_at: string | null
  entered_at: string
  due_at: string
  overdue: boolean
  closed_at: string | null
  outcome: string
  version: { id: number; number: number; program: { id: number; title: string } }
  permissions: { can_claim: boolean; can_release: boolean; can_decide: boolean }
}

export interface StageDecision {
  id: number
  stage: number
  user: UserRef
  decision: 'approve' | 'return'
  note: string
  created_at: string
}

export interface Submission {
  id: number
  version: number
  stages: WorkflowStage[]
  start_stage: number
  pre_submit: { reason?: string; critical?: Array<{ kind: string; node_key: string | null; block_key: string | null; competency_key: string | null }> }
  submitted_by: UserRef
  created_at: string
  outcome: '' | 'approved' | 'returned' | 'withdrawn' | 'cancelled'
  closed_at: string | null
  tasks: StageTask[]
  decisions: StageDecision[]
  previous: { version: { id: number; number: number }; decisions: StageDecision[] } | null
  resolved_must_fix: Array<{ id: number; body: string; quoted: string; author: UserRef; resolved_by: UserRef | null; resolved_at: string }>
}

export interface Member {
  id: number
  user: UserRef
  role: string
  created_at: string
  /** Whether the member has a second factor; given to admins only (they reset a lost one, D67). */
  mfa_enabled?: boolean
}

export interface AppNotification {
  id: number
  event: 'task_assigned' | 'version_returned' | 'version_approved' | 'task_due_soon' | 'task_due' | 'task_overdue'
  version: number | null
  params: { program?: string; program_id?: number; number?: number; stage_name?: string; due_at?: string | null; note?: string; responsible?: string }
  created_at: string
  read_at: string | null
}

export interface NotificationList {
  items: AppNotification[]
  unread: number
  email: 'immediate' | 'daily' | 'off'
}
