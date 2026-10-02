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

const KNOWN_CODES = new Set(['invalid_credentials', 'throttled', 'not_found', 'permission_denied', 'validation_error'])

export function errorCode(error: unknown): string {
  if (error instanceof ApiError) return KNOWN_CODES.has(error.code) ? error.code : error.status === 0 ? 'network' : 'unknown'
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

export const api = {
  me: () => request<SessionPayload>('/api/auth/me/'),
  login: (email: string, password: string) =>
    request<SessionPayload>('/api/auth/login/', { method: 'POST', body: { email, password } }),
  logout: () => request<void>('/api/auth/logout/', { method: 'POST' }),
  switchOrganization: (organizationId: number) =>
    request<SessionPayload>('/api/auth/switch-organization/', { method: 'POST', body: { organization_id: organizationId } }),
}
