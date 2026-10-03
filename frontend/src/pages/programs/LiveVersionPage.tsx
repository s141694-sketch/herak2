import {
  addBlock,
  addLink,
  addNode,
  blockFragment,
  DocumentRuleError,
  MAX_TITLE_LENGTH,
  moveNode,
  removeLink,
  renameNode,
  setBlockDeleted,
  setNodeDeleted,
} from '@harak2/shared'
import type { HocuspocusProvider } from '@hocuspocus/provider'
import type { Editor } from '@tiptap/core'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import type * as Y from 'yjs'

import { http } from '../../api'
import { useAuth } from '../../auth'
import { ErrorMessage } from '../../components/ErrorMessage'
import { StatusBadge } from '../../components/StatusBadge'
import { useAction, useResource } from '../../hooks/useResource'
import { LiveBlockEditor } from '../../live/LiveBlockEditor'
import { type Presence, usePresence } from '../../live/presence'
import { type LiveBlock, type LiveNode, type Snapshot, useSnapshot } from '../../live/snapshot'
import { announceCommentsChanged, type LiveDocument, useLiveDocument } from '../../live/useLiveDocument'
import { BLOCK_TYPES, type BlockType, type FrameworkVersionDetail, type ProgramComment, type ProgramVersionDetail } from '../../types'
import { CommentCard, type CommentContext, NewComment, placementOf } from './Comments'

interface Ctx {
  comments: CommentContext
  onEditor: (blockKey: string, editor: Editor | null) => void
  doc: Y.Doc
  provider: HocuspocusProvider
  me: { id: number; name: string }
  others: Presence[]
  snapshot: Snapshot
  editable: boolean
  levelCount: number
  framework: FrameworkVersionDetail | undefined
  levelName: (level: number) => string
  edit: (change: () => void) => void
}

/** A draft edited live through the collaboration service (phase 3). */
export function LiveVersionPage({
  version,
  framework,
  onSubmitted,
}: {
  version: ProgramVersionDetail
  framework: FrameworkVersionDetail | undefined
  onSubmitted: () => void
}) {
  const { t, i18n } = useTranslation()
  const live = useLiveDocument(version.id)
  const snapshot = useSnapshot(live?.doc)
  const { session } = useAuth()
  const me = useMemo(
    () => (session ? { id: session.user.id, name: session.user.full_name || session.user.email } : null),
    [session],
  )
  const others = usePresence(live?.provider, me)
  const navigate = useNavigate()
  const comments = useResource<ProgramComment[]>(`/api/programs/${version.program.id}/comments/`)
  const reloadComments = comments.reload
  const commentsVersion = live?.commentsVersion ?? 0
  useEffect(() => {
    if (commentsVersion > 0) reloadComments()
  }, [commentsVersion, reloadComments])
  const editors = useRef(new Map<string, Editor>())
  const [, setEditorsTick] = useState(0)
  const onEditor = useCallback((blockKey: string, editor: Editor | null) => {
    if (editor) editors.current.set(blockKey, editor)
    else editors.current.delete(blockKey)
    setEditorsTick((n) => n + 1)
  }, [])
  const action = useAction()
  const [ruleError, setRuleError] = useState<string | null>(null)
  const [showResolved, setShowResolved] = useState(false)

  const levels = version.template.levels
  const editable = Boolean(live && !live.locked && !live.frozen && live.mode === 'write' && live.status === 'connected' && live.synced)
  // Submitting while this editor holds changes the service has not confirmed could leave them out.
  const caughtUp = Boolean(live && live.status === 'connected' && live.synced && live.unsynced === 0 && !live.frozen)
  const role = session?.organization?.role
  // A version shows the comments made on it and on earlier versions, never those of a later one.
  const ownComments = (comments.data ?? []).filter((c) => c.version_number <= version.number)
  const resolvedCount = ownComments.filter((c) => c.status === 'resolved').length
  const commentContext: CommentContext | null = live && {
    programId: version.program.id,
    versionId: version.id,
    comments: ownComments.filter((c) => c.status === 'open' || showResolved),
    reload: () => {
      comments.reload()
      announceCommentsChanged(live.provider)
    },
    canResolve: version.permissions.collaborate,
    canReopen: role === 'reviewer' || role === 'approver' || role === 'admin',
    editorFor: (key) => editors.current.get(key),
    fragmentFor: (key) => {
      try {
        return blockFragment(live.doc, key)
      } catch {
        return undefined
      }
    },
    doc: live.doc,
    liveBlocks: shownBlocks(snapshot),
  }
  const ctx: Ctx | null = live && me && commentContext && {
    comments: commentContext,
    onEditor,
    doc: live.doc,
    provider: live.provider,
    me,
    others,
    snapshot,
    editable,
    levelCount: levels.length,
    framework,
    levelName: (level) => {
      const found = levels.find((l) => l.depth === level)
      return found ? (i18n.language === 'ar' ? found.name_ar : found.name_en) : ''
    },
    edit: (change) => {
      setRuleError(null)
      try {
        change()
      } catch (error) {
        if (error instanceof DocumentRuleError) setRuleError(error.code)
        else throw error
      }
    },
  }
  const roots = snapshot.nodes.filter((n) => n.parent === null)

  async function submit() {
    const done = await action.run(() => http.post(`/api/program-versions/${version.id}/submit/`))
    if (done) onSubmitted()
  }

  async function withdraw() {
    const done = await action.run(() => http.post(`/api/program-versions/${version.id}/withdraw/`))
    if (done) navigate(`/programs/${version.program.id}`)
  }

  return (
    <section className="card">
      <p>
        <Link to={`/programs/${version.program.id}`}>{version.program.title}</Link>
      </p>
      <h1>
        {t('common.version', { number: version.number })} <StatusBadge status={version.status} />
      </h1>
      <LiveStatusBar live={live} version={version} />
      {others.length > 0 && (
        <p className="row presence-here" data-testid="presence-here">
          {others.map((person) => (
            <span key={person.clientId} className="avatar" style={{ borderColor: person.color }}>
              {person.name}
            </span>
          ))}
        </p>
      )}
      <ErrorMessage code={action.error ?? ruleError} testId="version-error" />
      {version.permissions.collaborate && (
        <div className="row">
          {version.status === 'draft' && (
            <button type="button" className="primary-inline" data-testid="submit-version" disabled={action.busy || !caughtUp} onClick={() => void submit()}>
              {t('programs.submit')}
            </button>
          )}
          {version.status === 'draft' && !caughtUp && <span className="muted">{t('live.submitWaits')}</span>}
          {(version.status === 'submitted' || version.status === 'in_stage') && (
            <button type="button" className="secondary" data-testid="withdraw-version" disabled={action.busy} onClick={() => void withdraw()}>
              {t('programs.withdraw')}
            </button>
          )}
        </div>
      )}
      {resolvedCount > 0 && (
        <p>
          <button type="button" className="link-button" data-testid="toggle-resolved" onClick={() => setShowResolved((shown) => !shown)}>
            {showResolved ? t('comments.hideResolved', { count: resolvedCount }) : t('comments.showResolved', { count: resolvedCount })}
          </button>
        </p>
      )}
      {ctx && live?.everSynced && <Unanchored ctx={ctx} />}

      <h2>{t('programs.targets')}</h2>
      <ul className="plain" data-testid="version-targets">
        {version.targets.map((target) => (
          <li key={target.id}>
            <span dir="ltr">{target.code}</span> {target.title}
          </li>
        ))}
      </ul>

      <h2>{t('tree.title')}</h2>
      {ctx && live?.everSynced && (
        <div className="tree" data-testid="tree">
          {roots.length === 0 && <p className="muted">{t('tree.empty', { level: ctx.levelName(0) })}</p>}
          {roots.map((node) => (
            <NodeView key={node.key} node={node} ctx={ctx} />
          ))}
          {ctx.editable && <AddNode parent={null} ctx={ctx} />}
        </div>
      )}
    </section>
  )
}

function LiveStatusBar({ live, version }: { live: LiveDocument | null; version: ProgramVersionDetail }) {
  const { t, i18n } = useTranslation()
  if (!live) return null
  let message: string
  let tone = 'notice'
  if (live.authFailed) (message = t('live.authFailed')), (tone = 'error')
  else if (live.locked) (message = t('live.locked')), (tone = 'error')
  else if (live.frozen) message = t('live.frozen')
  else if (live.status === 'disconnected') (message = t('live.offline')), (tone = 'error')
  else if (live.status === 'connecting' || !live.synced) message = t('live.connecting')
  else if (live.mode === 'read') message = t('live.readOnly')
  else message = t('live.connected')
  const savedAt = version.live.materialized_at
  // Live news from the service wins over what the page loaded with. The reason comes from its code: the
  // message itself is technical and in English.
  const saveErrorCode =
    live.saveError !== undefined ? (live.saveError === null ? null : (live.saveErrorCode ?? 'document_invalid')) : version.live.last_error_code
  return (
    <div className="live-status">
      <p className={tone} data-testid="live-status" data-state={live.locked ? 'locked' : live.frozen ? 'frozen' : live.status} data-mode={live.mode ?? ''}>
        {message}
      </p>
      {saveErrorCode && (
        <p className="error" data-testid="live-save-error">
          {t('live.saveError', { reason: t(`live.saveErrors.${saveErrorCode}`, { defaultValue: t('live.saveErrors.document_invalid') }) })}
        </p>
      )}
      {savedAt && <p className="muted">{t('live.lastSaved', { time: new Date(savedAt).toLocaleString(i18n.language) })}</p>}
    </div>
  )
}

function AddNode({ parent, ctx }: { parent: LiveNode | null; ctx: Ctx }) {
  const { t } = useTranslation()
  const [title, setTitle] = useState('')
  const level = parent ? parent.level + 1 : 0
  if (level >= ctx.levelCount) return null
  const label = t(parent ? 'tree.addChild' : 'tree.addRoot', { level: ctx.levelName(level) })
  return (
    <form
      className="row add-node"
      onSubmit={(event) => {
        event.preventDefault()
        ctx.edit(() => addNode(ctx.doc, { parent: parent?.key ?? null, title }, ctx.levelCount))
        setTitle('')
      }}
    >
      <input required aria-label={label} placeholder={label} value={title} maxLength={MAX_TITLE_LENGTH} onChange={(e) => setTitle(e.target.value)} />
      <button type="submit" className="secondary">
        {t('common.add')}
      </button>
    </form>
  )
}

function NodeView({ node, ctx }: { node: LiveNode; ctx: Ctx }) {
  const { t } = useTranslation()
  const [renaming, setRenaming] = useState(false)
  const [title, setTitle] = useState(node.title)
  const children = ctx.snapshot.nodes.filter((n) => n.parent === node.key)
  const blocks = ctx.snapshot.blocks.filter((b) => b.node_key === node.key)
  const possibleParents = ctx.snapshot.nodes.filter((n) => !n.deleted && n.level === node.level - 1 && n.key !== node.parent)

  return (
    <div className={node.deleted ? 'node deleted' : 'node'} data-testid={`node-${node.title}`} data-level={node.level}>
      <div className="node-header">
        <span className="badge">{ctx.levelName(node.level)}</span>
        {renaming && ctx.editable ? (
          <form
            className="row"
            onSubmit={(event) => {
              event.preventDefault()
              ctx.edit(() => renameNode(ctx.doc, node.key, title))
              setRenaming(false)
            }}
          >
            <input
              aria-label={t('tree.nodeTitle')}
              value={title}
              maxLength={MAX_TITLE_LENGTH}
              data-testid="rename-input"
              onChange={(e) => setTitle(e.target.value)}
            />
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
            <button
              type="button"
              className="link-button"
              data-testid="rename-node"
              onClick={() => {
                setTitle(node.title)
                setRenaming(true)
              }}
            >
              {t('common.rename')}
            </button>
            <button type="button" className="link-button" onClick={() => ctx.edit(() => setNodeDeleted(ctx.doc, node.key, !node.deleted))}>
              {node.deleted ? t('common.restore') : t('common.delete')}
            </button>
            {node.level > 0 && possibleParents.length > 0 && (
              <select
                aria-label={t('tree.moveTo')}
                value=""
                data-testid="move-node"
                onChange={(e) => ctx.edit(() => moveNode(ctx.doc, node.key, { parent: e.target.value }, ctx.levelCount))}
              >
                <option value="">{t('tree.moveTo')}</option>
                {possibleParents.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.title}
                  </option>
                ))}
              </select>
            )}
          </span>
        )}
      </div>
      {!node.deleted && (
        <div className="node-body">
          {blocks.map((block) => (
            <BlockView key={block.key} block={block} ctx={ctx} />
          ))}
          {ctx.editable && <AddBlock node={node} ctx={ctx} />}
          {children.map((child) => (
            <NodeView key={child.key} node={child} ctx={ctx} />
          ))}
          {ctx.editable && <AddNode parent={node} ctx={ctx} />}
        </div>
      )}
    </div>
  )
}

function AddBlock({ node, ctx }: { node: LiveNode; ctx: Ctx }) {
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
      <button type="button" className="secondary" onClick={() => ctx.edit(() => addBlock(ctx.doc, { node_key: node.key, type }))}>
        {t('tree.addBlock')}
      </button>
    </div>
  )
}

function BlockView({ block, ctx }: { block: LiveBlock; ctx: Ctx }) {
  const { t } = useTranslation()
  return (
    <div className={block.deleted ? 'block deleted' : 'block'} data-testid={`block-${block.type}`} data-block-key={block.key}>
      <div className="block-header">
        <span className={`badge badge-${block.type}`}>{t(`blockType.${block.type}`)}</span>
        {block.deleted && <span className="muted">{t('common.deleted')}</span>}
        {ctx.others
          .filter((person) => person.block === block.key)
          .map((person) => (
            <span key={person.clientId} className="avatar editing" style={{ borderColor: person.color }} data-testid="block-presence">
              {t('live.editing', { name: person.name })}
            </span>
          ))}
        {ctx.editable && (
          <button type="button" className="link-button" onClick={() => ctx.edit(() => setBlockDeleted(ctx.doc, block.key, !block.deleted))}>
            {block.deleted ? t('common.restore') : t('common.delete')}
          </button>
        )}
      </div>
      {!block.deleted && (
        <>
          <LiveBlockEditor doc={ctx.doc} provider={ctx.provider} blockKey={block.key} editable={ctx.editable} me={ctx.me} onEditor={ctx.onEditor} />
          <Alignment block={block} ctx={ctx} />
          <BlockComments block={block} ctx={ctx} />
        </>
      )}
    </div>
  )
}

function Alignment({ block, ctx }: { block: LiveBlock; ctx: Ctx }) {
  const { t } = useTranslation()
  const outgoing = ctx.snapshot.links.filter((link) => link.source_key === block.key)
  const objectives = ctx.snapshot.blocks.filter((b) => b.type === 'objective' && !b.deleted && b.key !== block.key)
  const competencies = ctx.framework?.competencies ?? []
  const nodeOf = (key: string) => ctx.snapshot.nodes.find((n) => n.key === key)
  const ancestors = new Set<string>()
  for (let cursor = nodeOf(block.node_key)?.parent ?? null; cursor !== null; cursor = nodeOf(cursor)?.parent ?? null) {
    if (ancestors.has(cursor)) break
    ancestors.add(cursor)
  }
  const objectiveLabel = (key: string | null) => {
    const index = objectives.findIndex((o) => o.key === key)
    return index === -1 ? '' : `${t('blockType.objective')} ${index + 1}`
  }

  type Option = { kind: 'objective_competency' | 'assessment_objective' | 'objective_parent'; label: string; choices: Array<{ value: string; label: string }> }
  const options: Option[] = []
  if (block.type === 'objective') {
    options.push({ kind: 'objective_competency', label: t('alignment.competencies'), choices: competencies.map((c) => ({ value: c.competency_key, label: `${c.code} ${c.title}` })) })
    options.push({
      kind: 'objective_parent',
      label: t('alignment.parents'),
      choices: objectives.filter((o) => ancestors.has(o.node_key)).map((o) => ({ value: o.key, label: objectiveLabel(o.key) })),
    })
  }
  if (block.type === 'assessment') {
    options.push({ kind: 'assessment_objective', label: t('alignment.objectives'), choices: objectives.map((o) => ({ value: o.key, label: objectiveLabel(o.key) })) })
  }
  if (options.length === 0) return null

  return (
    <div className="alignment" data-testid="alignment">
      {options.map((option) => (
        <div className="row" key={option.kind}>
          <span className="muted">{option.label}</span>
          {outgoing
            .filter((link) => link.kind === option.kind)
            .map((link) => (
              <span className="chip" key={link.key}>
                {link.competency_key ? (competencies.find((c) => c.competency_key === link.competency_key)?.code ?? '') : objectiveLabel(link.target_key)}
                {ctx.editable && (
                  <button type="button" className="link-button" onClick={() => ctx.edit(() => removeLink(ctx.doc, link.key))}>
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
              onChange={(e) =>
                ctx.edit(() =>
                  addLink(
                    ctx.doc,
                    option.kind === 'objective_competency'
                      ? { kind: option.kind, source_key: block.key, competency_key: e.target.value }
                      : { kind: option.kind, source_key: block.key, target_key: e.target.value },
                  ),
                )
              }
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
      ))}
    </div>
  )
}

/** Blocks a person can see in the tree: not deleted, and not inside a deleted node (whose body is hidden). */
function shownBlocks(snapshot: Snapshot): Set<string> {
  const nodes = new Map(snapshot.nodes.map((node) => [node.key, node]))
  const hidden = (key: string | null) => {
    const seen = new Set<string>()
    for (let cursor = key; cursor !== null && !seen.has(cursor); cursor = nodes.get(cursor)?.parent ?? null) {
      seen.add(cursor)
      const node = nodes.get(cursor)
      if (!node || node.deleted) return true
    }
    return false
  }
  return new Set(snapshot.blocks.filter((block) => !block.deleted && !hidden(block.node_key)).map((block) => block.key))
}

/** Re-renders its caller on every change of the document, throttled to animation frames. */
function useDocTick(doc: Y.Doc): number {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let frame = 0
    const bump = () => {
      if (frame) return
      frame = requestAnimationFrame(() => {
        frame = 0
        setTick((n) => n + 1)
      })
    }
    doc.on('update', bump)
    return () => {
      doc.off('update', bump)
      if (frame) cancelAnimationFrame(frame)
    }
  }, [doc])
  return tick
}

function BlockComments({ block, ctx }: { block: LiveBlock; ctx: Ctx }) {
  useDocTick(ctx.doc)
  const here = ctx.comments.comments
    .filter((c) => c.block_key === block.key)
    .map((c) => ({ comment: c, ...placementOf(c, ctx.comments) }))
    .filter((entry) => entry.placement !== 'orphaned')
  return (
    <div className="comments" data-testid="block-comments">
      {here.map(({ comment, placement, resolved }) => (
        <CommentCard key={comment.id} comment={comment} ctx={ctx.comments} placement={placement} resolved={resolved} />
      ))}
      <NewComment blockKey={block.key} ctx={ctx.comments} />
    </div>
  )
}

function Unanchored({ ctx }: { ctx: Ctx }) {
  const { t } = useTranslation()
  useDocTick(ctx.doc)
  const orphaned = ctx.comments.comments
    .filter((c) => c.block_key)
    .map((c) => ({ comment: c, ...placementOf(c, ctx.comments) }))
    .filter((entry) => entry.placement === 'orphaned')
  if (orphaned.length === 0) return null
  return (
    <section className="panel" data-testid="unanchored-comments">
      <h2>{t('comments.unanchored')}</h2>
      <p className="muted">{t('comments.unanchoredHint')}</p>
      {orphaned.map(({ comment, placement }) => (
        <CommentCard key={comment.id} comment={comment} ctx={ctx.comments} placement={placement} />
      ))}
    </section>
  )
}
