/** Thin client for the Django API: same-origin session cookies plus the CSRF header on writes. */

export type Role = 'admin' | 'author' | 'reviewer' | 'approver' | 'pending'

export interface SessionUser {
  id: number
  email: string
  full_name: string
}

export interface OrganizationSummary {
  id: number
  name: string
  slug: string
}

export interface SessionPayload {
  user: SessionUser
  organization: (OrganizationSummary & { role: Role }) | null
  memberships: Array<{ organization: OrganizationSummary; role: Role }>
}

/** A failed call. `code` is a stable key the UI translates under `errors.*`. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

/** The stable code of a failure; the UI looks it up under `errors.*` and falls back to `errors.unknown`. */
export function errorCode(error: unknown): string {
  if (error instanceof ApiError) return error.status === 0 ? 'network' : error.code
  return 'unknown'
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

async function ensureCsrf(): Promise<void> {
  if (!csrfToken()) await fetch('/api/auth/csrf/', { credentials: 'same-origin' })
}

export async function request<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = init.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') {
    await ensureCsrf()
    headers['Content-Type'] = 'application/json'
    headers['X-CSRFToken'] = csrfToken()
  }
  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    })
  } catch {
    throw new ApiError(0, 'network', 'network error')
  }
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const error = body?.error ?? {}
    throw new ApiError(response.status, error.code ?? 'unknown', error.message ?? response.statusText)
  }
  return body as T
}

async function send<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, { credentials: 'same-origin', ...init })
  } catch {
    throw new ApiError(0, 'network', 'network error')
  }
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const error = body?.error ?? {}
    throw new ApiError(response.status, error.code ?? 'unknown', error.message ?? response.statusText)
  }
  return body as T
}

export const http = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  /** Multipart upload of a single file in the `file` field. */
  upload: async <T>(path: string, file: File): Promise<T> => {
    await ensureCsrf()
    const form = new FormData()
    form.append('file', file)
    return send<T>(path, { method: 'POST', body: form, headers: { 'X-CSRFToken': csrfToken(), Accept: 'application/json' } })
  },
}

export const api = {
  me: () => request<SessionPayload>('/api/auth/me/'),
  login: (email: string, password: string) =>
    request<SessionPayload>('/api/auth/login/', { method: 'POST', body: { email, password } }),
  logout: () => request<void>('/api/auth/logout/', { method: 'POST' }),
  switchOrganization: (organizationId: number) =>
    request<SessionPayload>('/api/auth/switch-organization/', { method: 'POST', body: { organization_id: organizationId } }),
}
