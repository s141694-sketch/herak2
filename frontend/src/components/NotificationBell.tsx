import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { http } from '../api'
import { useAction, useResource } from '../hooks/useResource'
import type { AppNotification, NotificationList } from '../types'

const REFRESH_MS = 60_000

/** One notification in the interface's language (the email carries both). */
export function useNotificationText() {
  const { t, i18n } = useTranslation()
  return (n: AppNotification) => {
    const due = n.params.due_at ? new Date(n.params.due_at).toLocaleString(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }) : ''
    return t(`notifications.events.${n.event}`, {
      program: n.params.program ?? '',
      number: n.params.number ?? '',
      stage: n.params.stage_name ?? '',
      due,
      note: n.params.note ?? '',
      responsible: n.params.responsible ?? '',
    })
  }
}

/** The bell in the top bar (spec 6.5): unread count, the latest notifications, and how email follows them. */
export function NotificationBell() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const list = useResource<NotificationList>('/api/notifications/')
  const action = useAction()
  const [open, setOpen] = useState(false)
  const text = useNotificationText()
  const { reload } = list

  useEffect(() => {
    const timer = setInterval(reload, REFRESH_MS)
    return () => clearInterval(timer)
  }, [reload])

  const post = async (body: Record<string, unknown>) => {
    if (await action.run(() => http.post('/api/notifications/', body))) reload()
  }
  const follow = async (n: AppNotification) => {
    if (!n.read_at) await action.run(() => http.post(`/api/notifications/${n.id}/read/`))
    setOpen(false)
    reload()
    if (n.version) navigate(`/program-versions/${n.version}`)
  }
  const unread = list.data?.unread ?? 0

  return (
    <div className="bell">
      <button
        type="button"
        className="link-button"
        aria-expanded={open}
        aria-label={t('notifications.title', { count: unread })}
        data-testid="notifications-toggle"
        onClick={() => {
          setOpen((value) => !value)
          reload()
        }}
      >
        {t('notifications.bell')}
        {unread > 0 && (
          <span className="badge badge-returned" data-testid="notifications-unread">
            {unread}
          </span>
        )}
      </button>
      {open && list.data && (
        <div className="bell-panel" role="dialog" aria-label={t('notifications.title', { count: unread })} data-testid="notifications-panel">
          {list.data.items.length === 0 && <p className="muted">{t('notifications.none')}</p>}
          <ul className="plain">
            {list.data.items.map((n) => (
              <li key={n.id} className={n.read_at ? 'read' : 'unread'} data-testid="notification" data-event={n.event}>
                <button type="button" className="link-button" onClick={() => void follow(n)}>
                  {text(n)}
                </button>
              </li>
            ))}
          </ul>
          <div className="row">
            {unread > 0 && (
              <button type="button" className="secondary" data-testid="notifications-read-all" onClick={() => void post({ read_all: true })}>
                {t('notifications.readAll')}
              </button>
            )}
            <label className="inline">
              <span>{t('notifications.email')}</span>
              <select value={list.data.email} data-testid="notifications-email" onChange={(e) => void post({ email: e.target.value })}>
                {(['immediate', 'daily', 'off'] as const).map((mode) => (
                  <option key={mode} value={mode}>
                    {t(`notifications.emailMode.${mode}`)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      )}
    </div>
  )
}
