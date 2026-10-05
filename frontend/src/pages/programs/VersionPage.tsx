import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router'

import { http } from '../../api'
import { useAuth } from '../../auth'
import { BlockEditor } from '../../components/BlockEditor'
import { ErrorMessage, Loading } from '../../components/ErrorMessage'
import { StatusBadge } from '../../components/StatusBadge'
import { useAction, useResource } from '../../hooks/useResource'
import { canWithdraw, ReviewPanel, useVersionWorkflow } from '../workflows/ReviewPanel'
import { LiveVersionPage } from './LiveVersionPage'
import {
  type AlignmentLink,
  BLOCK_TYPES,
  type BlockType,
  type FrameworkVersionDetail,
  type ProgramVersionDetail,
  type Tree,
  type TreeBlock,
  type TreeNode,
} from '../../types'

interface Ctx {
  version: ProgramVersionDetail
  tree: Tree
  links: AlignmentLink[]
  framework: FrameworkVersionDetail | undefined
  editable: boolean
  levelName: (level: number) => string
  act: <T>(action: () => Promise<T>) => Promise<T | undefined>
  refresh: () => void
}

export function VersionPage() {
  const { t, i18n } = useTranslation()
  const { id } = useParams()
  const navigate = useNavigate()
  const version = useResource<ProgramVersionDetail>(`/api/program-versions/${id}/`)
  const tree = useResource<Tree>(`/api/program-versions/${id}/tree/`)
  const links = useResource<AlignmentLink[]>(`/api/program-versions/${id}/alignment-links/`)
  const framework = useResource<FrameworkVersionDetail>(version.data ? `/api/framework-versions/${version.data.framework.id}/` : null)
  const action = useAction()
  const workflow = useVersionWorkflow(Number(id))
  const { session } = useAuth()
  const role = session?.organization?.role

  if ((version.loading && !version.data) || (tree.loading && !tree.data)) return <Loading />
  if (!version.data || !tree.data) return <ErrorMessage code={version.error ?? tree.error} />

  const refresh = () => {
    workflow.reload()
    version.reload()
    tree.reload()
    links.reload()
  }
  // A draft is edited live. A locked version that was edited live opens read-only on its frozen
  // live state, so comments anchor against the same Yjs items as the next draft (decision D2).
  if (version.data.status === 'draft' || version.data.live.is_live) {
    // Keyed by version: moving to another version inside the app starts its page afresh (a reason typed for one
    // submission must not carry to the next).
    return <LiveVersionPage key={version.data.id} version={version.data} framework={framework.data} onSubmitted={refresh} />
  }
  const levels = version.data.template.levels
  const ctx: Ctx = {
    version: version.data,
    tree: tree.data,
    links: links.data ?? [],
    framework: framework.data,
    editable: version.data.permissions.edit,
    levelName: (level) => {
      const found = levels.find((l) => l.depth === level)
      return found ? (i18n.language === 'ar' ? found.name_ar : found.name_en) : ''
    },
    act: (fn) => action.run(fn),
    refresh,
  }
  const roots = tree.data.nodes.filter((n) => n.parent === null).sort((a, b) => a.order - b.order)
  const { status } = version.data

  async function transition(path: 'withdraw') {
    const done = await action.run(() => http.post(`/api/program-versions/${id}/${path}/`))
    if (done) navigate(`/programs/${version.data!.program.id}`)
  }

  return (
    <section className="card">
      <p>
        <Link to={`/programs/${version.data.program.id}`}>{version.data.program.title}</Link>
      </p>
      <h1>
        {t('common.version', { number: version.data.number })} <StatusBadge status={status} />
      </h1>
      <ErrorMessage code={action.error} testId="version-error" />
      {!ctx.editable && <p className="notice">{t('programs.readOnly')}</p>}
      <div className="row">
        {version.data.permissions.collaborate && canWithdraw(workflow.data) && (
          <button type="button" className="secondary" data-testid="withdraw-version" onClick={() => void transition('withdraw')}>
            {t('programs.withdraw')}
          </button>
        )}
      </div>

      <ReviewPanel
        workflow={workflow}
        programId={version.data.program.id}
        canReopen={role === 'reviewer' || role === 'approver' || role === 'admin'}
        onChanged={refresh}
        onCommentsChanged={refresh}
      />

      <h2>{t('programs.targets')}</h2>
      <ul className="plain" data-testid="version-targets">
        {version.data.targets.map((target) => (
          <li key={target.id}>
            <span dir="ltr">{target.code}</span> {target.title}
          </li>
        ))}
      </ul>

      <h2>{t('tree.title')}</h2>
      <div className="tree" data-testid="tree">
        {roots.length === 0 && <p className="muted">{t('tree.empty', { level: ctx.levelName(0) })}</p>}
        {roots.map((node) => (
          <NodeView key={node.id} node={node} ctx={ctx} />
        ))}
        {ctx.editable && <AddNode parent={null} ctx={ctx} />}
      </div>
    </section>
  )
}

function AddNode({ parent, ctx }: { parent: TreeNode | null; ctx: Ctx }) {
  const { t } = useTranslation()
  const [title, setTitle] = useState('')
  const level = parent ? parent.level + 1 : 0
  if (level >= ctx.version.template.levels.length) return null
  const label = parent ? t('tree.addChild', { level: ctx.levelName(level) }) : t('tree.addRoot', { level: ctx.levelName(level) })

  return (
    <form
      className="row add-node"
      data-testid={`add-node-${parent ? parent.node_key : 'root'}`}
      onSubmit={(event) => {
        event.preventDefault()
        void ctx
          .act(() => http.post(`/api/program-versions/${ctx.version.id}/nodes/`, { title, parent: parent?.id ?? null }))
          .then((created) => {
            if (created) {
              setTitle('')
              ctx.refresh()
            }
          })
      }}
    >
      <input required aria-label={label} placeholder={label} value={title} onChange={(e) => setTitle(e.target.value)} />
      <button type="submit" className="secondary">
        {t('common.add')}
      </button>
    </form>
  )
}

function NodeView({ node, ctx }: { node: TreeNode; ctx: Ctx }) {
  const { t } = useTranslation()
  const [renaming, setRenaming] = useState(false)
  const [title, setTitle] = useState(node.title)
  const children = ctx.tree.nodes.filter((n) => n.parent === node.id).sort((a, b) => a.order - b.order)
  const blocks = ctx.tree.blocks.filter((b) => b.node === node.id).sort((a, b) => a.order - b.order)

  return (
    <div className={node.deleted ? 'node deleted' : 'node'} data-testid={`node-${node.title}`} data-level={node.level}>
      <div className="node-header">
        <span className="badge">{ctx.levelName(node.level)}</span>
        {renaming ? (
          <form
            className="row"
            onSubmit={(event) => {
              event.preventDefault()
              void ctx.act(() => http.patch(`/api/program-nodes/${node.id}/`, { title })).then(() => {
                setRenaming(false)
                ctx.refresh()
              })
            }}
          >
            <input aria-label={t('tree.nodeTitle')} value={title} data-testid="rename-input" onChange={(e) => setTitle(e.target.value)} />
            <button type="submit" className="secondary">
              {t('common.save')}
            </button>
          </form>
        ) : (
          <strong>{node.title}</strong>
        )}
        {node.deleted && <span className="muted">{t('common.deleted')}</span>}
        {ctx.editable && !renaming && (
          <span className="node-actions">
            <button type="button" className="link-button" data-testid="rename-node" onClick={() => setRenaming(true)}>
              {t('common.rename')}
            </button>
            <button
              type="button"
              className="link-button"
              onClick={() =>
                void ctx
                  .act(() => (node.deleted ? http.post(`/api/program-nodes/${node.id}/restore/`) : http.del(`/api/program-nodes/${node.id}/`)))
                  .then(ctx.refresh)
              }
            >
              {node.deleted ? t('common.restore') : t('common.delete')}
            </button>
            <MoveNode node={node} ctx={ctx} />
          </span>
        )}
      </div>
      {!node.deleted && (
        <div className="node-body">
          {blocks.map((block) => (
            <BlockView key={block.id} block={block} ctx={ctx} />
          ))}
          {ctx.editable && <AddBlock node={node} ctx={ctx} />}
          {children.map((child) => (
            <NodeView key={child.id} node={child} ctx={ctx} />
          ))}
          {ctx.editable && <AddNode parent={node} ctx={ctx} />}
        </div>
      )}
    </div>
  )
}

function descendantsOf(node: TreeNode, nodes: TreeNode[]): Set<number> {
  const found = new Set<number>([node.id])
  let grew = true
  while (grew) {
    grew = false
    for (const n of nodes) if (n.parent !== null && found.has(n.parent) && !found.has(n.id)) (found.add(n.id), (grew = true))
  }
  return found
}

function MoveNode({ node, ctx }: { node: TreeNode; ctx: Ctx }) {
  const { t } = useTranslation()
  const excluded = descendantsOf(node, ctx.tree.nodes)
  const parents = ctx.tree.nodes.filter((n) => !excluded.has(n.id) && !n.deleted && n.level === node.level - 1 && n.id !== node.parent)
  if (node.level === 0 || parents.length === 0) return null
  return (
    <select
      aria-label={t('tree.moveTo')}
      value=""
      data-testid="move-node"
      onChange={(e) =>
        void ctx.act(() => http.post(`/api/program-nodes/${node.id}/move/`, { parent: Number(e.target.value), order: 999 })).then(ctx.refresh)
      }
    >
      <option value="">{t('tree.moveTo')}</option>
      {parents.map((p) => (
        <option key={p.id} value={p.id}>
          {p.title}
        </option>
      ))}
    </select>
  )
}

function AddBlock({ node, ctx }: { node: TreeNode; ctx: Ctx }) {
  const { t } = useTranslation()
  const [type, setType] = useState<BlockType>('objective')
  return (
    <div className="row add-block" data-testid={`add-block-${node.title}`}>
      <select aria-label={t('tree.blockType')} value={type} onChange={(e) => setType(e.target.value as BlockType)}>
        {BLOCK_TYPES.map((value) => (
          <option key={value} value={value}>
            {t(`blockType.${value}`)}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="secondary"
        onClick={() => void ctx.act(() => http.post(`/api/program-versions/${ctx.version.id}/blocks/`, { node: node.id, type })).then(ctx.refresh)}
      >
        {t('tree.addBlock')}
      </button>
    </div>
  )
}

function BlockView({ block, ctx }: { block: TreeBlock; ctx: Ctx }) {
  const { t } = useTranslation()
  return (
    <div className={block.deleted ? 'block deleted' : 'block'} data-testid={`block-${block.type}`} data-block-key={block.block_key}>
      <div className="block-header">
        <span className={`badge badge-${block.type}`}>{t(`blockType.${block.type}`)}</span>
        {block.deleted && <span className="muted">{t('common.deleted')}</span>}
        {ctx.editable && (
          <button
            type="button"
            className="link-button"
            onClick={() =>
              void ctx
                .act(() => (block.deleted ? http.post(`/api/program-blocks/${block.id}/restore/`) : http.del(`/api/program-blocks/${block.id}/`)))
                .then(ctx.refresh)
            }
          >
            {block.deleted ? t('common.restore') : t('common.delete')}
          </button>
        )}
      </div>
      {!block.deleted && (
        <>
          <BlockEditor
            content={block.content}
            editable={ctx.editable}
            onSave={async (content) => (await ctx.act(() => http.patch(`/api/program-blocks/${block.id}/`, { content }))) !== undefined}
          />
          <Alignment block={block} ctx={ctx} />
        </>
      )}
    </div>
  )
}

function Alignment({ block, ctx }: { block: TreeBlock; ctx: Ctx }) {
  const { t } = useTranslation()
  const outgoing = ctx.links.filter((link) => link.source === block.id)
  const objectives = ctx.tree.blocks.filter((b) => b.type === 'objective' && !b.deleted && b.id !== block.id)
  const node = ctx.tree.nodes.find((n) => n.id === block.node)
  const ancestors = new Set<number>()
  let cursor = node?.parent ?? null
  while (cursor !== null) {
    ancestors.add(cursor)
    cursor = ctx.tree.nodes.find((n) => n.id === cursor)?.parent ?? null
  }

  const options: Array<{ kind: AlignmentLink['kind']; label: string; choices: Array<{ value: number; label: string }> }> = []
  if (block.type === 'objective') {
    options.push({
      kind: 'objective_competency',
      label: t('alignment.competencies'),
      choices: (ctx.framework?.competencies ?? []).map((c) => ({ value: c.id, label: `${c.code} ${c.title}` })),
    })
    options.push({
      kind: 'objective_parent',
      label: t('alignment.parents'),
      choices: objectives.filter((o) => ancestors.has(o.node)).map((o) => ({ value: o.id, label: textOf(o) })),
    })
  }
  if (block.type === 'assessment') {
    options.push({ kind: 'assessment_objective', label: t('alignment.objectives'), choices: objectives.map((o) => ({ value: o.id, label: textOf(o) })) })
  }
  if (options.length === 0) return null

  return (
    <div className="alignment" data-testid="alignment">
      {options.map((option) => {
        const existing = outgoing.filter((link) => link.kind === option.kind)
        return (
          <div className="row" key={option.kind}>
            <span className="muted">{option.label}</span>
            {existing.map((link) => (
              <span className="chip" key={link.id}>
                {link.target_competency_code ?? textOf(ctx.tree.blocks.find((b) => b.id === link.target_block))}
                {ctx.editable && (
                  <button type="button" className="link-button" onClick={() => void ctx.act(() => http.del(`/api/alignment-links/${link.id}/`)).then(ctx.refresh)}>
                    {t('programs.remove')}
                  </button>
                )}
              </span>
            ))}
            {ctx.editable && option.choices.length > 0 && (
              <select
                aria-label={option.label}
                value=""
                data-testid={`link-${option.kind}`}
                onChange={(e) => {
                  const value = Number(e.target.value)
                  const body =
                    option.kind === 'objective_competency'
                      ? { kind: option.kind, source: block.id, target_competency: value }
                      : { kind: option.kind, source: block.id, target_block: value }
                  void ctx.act(() => http.post(`/api/program-versions/${ctx.version.id}/alignment-links/`, body)).then(ctx.refresh)
                }}
              >
                <option value="">{t('alignment.choose')}</option>
                {option.choices.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label}
                  </option>
                ))}
              </select>
            )}
          </div>
        )
      })}
    </div>
  )
}

function textOf(block: TreeBlock | undefined): string {
  if (!block) return ''
  const parts: string[] = []
  const walk = (node: unknown) => {
    if (!node || typeof node !== 'object') return
    const record = node as { type?: string; text?: string; content?: unknown[] }
    if (record.type === 'text' && record.text) parts.push(record.text)
    record.content?.forEach(walk)
  }
  walk(block.content)
  const text = parts.join(' ').trim()
  return text.length > 60 ? `${text.slice(0, 60)}…` : text
}
