import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'

import { ErrorMessage, Loading } from '../../components/ErrorMessage'
import { useResource } from '../../hooks/useResource'
import type { Diff } from '../../types'

export function DiffPage() {
  const { t } = useTranslation()
  const { id, from, to } = useParams()
  const diff = useResource<Diff>(`/api/program-versions/${from}/diff/${to}/`)
  const [showUnchanged, setShowUnchanged] = useState(false)

  if (diff.loading && !diff.data) return <Loading />
  if (!diff.data) return <ErrorMessage code={diff.error} />
  const { nodes, blocks, links, targets, summary } = diff.data
  const visible = <T extends { change: string }>(entries: T[]) => entries.filter((e) => showUnchanged || e.change !== 'unchanged')

  return (
    <section className="card" data-testid="diff">
      <p>
        <Link to={`/programs/${id}`}>{t('common.back')}</Link>
      </p>
      <h1>{t('diff.title', { from: diff.data.from.number, to: diff.data.to.number })}</h1>
      <label className="row">
        <input type="checkbox" checked={showUnchanged} onChange={(e) => setShowUnchanged(e.target.checked)} />
        {t('diff.showUnchanged')}
      </label>

      <h2>{t('diff.nodes')}</h2>
      <p data-testid="diff-nodes-summary">{t('diff.summary', summary.nodes)}</p>
      <ul className="plain">
        {visible(nodes).map((entry) => (
          <li key={entry.node_key} className={`change change-${entry.change}`} data-change={entry.change}>
            <span className="badge">{t(`change.${entry.change}`)}</span>{' '}
            {String((entry.after ?? entry.before)?.title ?? '')}
            {entry.change === 'modified' && entry.before && entry.after && (
              <span className="muted">
                {' '}
                {t('diff.before')}: {String(entry.before.title)}
              </span>
            )}
            {entry.fields.length > 0 && <span className="muted"> ({entry.fields.map((f) => t(`field.${f}`)).join('، ')})</span>}
          </li>
        ))}
      </ul>

      <h2>{t('diff.blocks')}</h2>
      <p data-testid="diff-blocks-summary">{t('diff.summary', summary.blocks)}</p>
      <ul className="plain">
        {visible(blocks).map((entry) => (
          <li key={entry.block_key} className={`change change-${entry.change}`} data-change={entry.change}>
            <span className="badge">{t(`change.${entry.change}`)}</span>{' '}
            <span className="badge">{t(`blockType.${String((entry.after ?? entry.before)?.type)}`)}</span>
            {entry.change === 'modified' ? (
              <div className="diff-text">
                <p className="removed-text">
                  {t('diff.before')}: {entry.text_before}
                </p>
                <p className="added-text">
                  {t('diff.after')}: {entry.text_after}
                </p>
              </div>
            ) : (
              <span> {entry.text_after ?? entry.text_before}</span>
            )}
          </li>
        ))}
      </ul>

      <h2>{t('diff.links')}</h2>
      {links.added.length + links.removed.length === 0 && <p className="muted">{t('diff.noChanges')}</p>}
      <ul className="plain">
        {links.added.map((link, i) => (
          <li key={`a${i}`} data-change="added">
            {t('diff.added')}: {link.competency_code ?? link.kind}
          </li>
        ))}
        {links.removed.map((link, i) => (
          <li key={`r${i}`} data-change="removed">
            {t('diff.removed')}: {link.competency_code ?? link.kind}
          </li>
        ))}
      </ul>

      <h2>{t('diff.targets')}</h2>
      {targets.added.length + targets.removed.length === 0 && <p className="muted">{t('diff.noChanges')}</p>}
      <ul className="plain">
        {targets.added.map((c) => (
          <li key={`a${c.code}`}>
            {t('diff.added')}: <span dir="ltr">{c.code}</span> {c.title}
          </li>
        ))}
        {targets.removed.map((c) => (
          <li key={`r${c.code}`}>
            {t('diff.removed')}: <span dir="ltr">{c.code}</span> {c.title}
          </li>
        ))}
      </ul>
    </section>
  )
}
