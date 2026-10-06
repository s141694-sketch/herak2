/** Thin client for the Django API: same-origin session cookies plus the CSRF header on writes. */

export type Role = 'admin' | 'author' | 'reviewer' | 'approver' | 'pending'

export interface SessionUser {
  id: number
  email: string
  full_name: string
  /** Whether this person uses a second factor (D67). */
  mfa_enabled: boolean
}

export interface OrganizationSummary {
  id: number
  name: string
  slug: string
}

export interface SessionPayload {
  user: SessionUser
  organization: (OrganizationSummary & { role: Role }) | null
  /** What the organization asks of this session first: its provider (D66), a password (a session opened by another
   * organization's provider, D71) or a second factor (D67). */
  memberships: Membership[]
}

export interface Membership {
  organization: OrganizationSummary
  role: Role
  sso_required: boolean
  password_required: boolean
  mfa_required: boolean
}

/** A password that was right, from someone whose second factor is still to be checked. */
export interface MfaPending {
  mfa_required: true
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

/** A refusal without Harak's error body: a body over the proxy's limit (413) is refused before it reaches the server,
 * and the only uploads that large are curricula for an import. */
function fallbackCode(status: number): string {
  return status === 413 ? 'import_file_too_large' : 'unknown'
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
    throw new ApiError(response.status, error.code ?? fallbackCode(response.status), error.message ?? response.statusText)
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
    throw new ApiError(response.status, error.code ?? fallbackCode(response.status), error.message ?? response.statusText)
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
    request<SessionPayload | MfaPending>('/api/auth/login/', { method: 'POST', body: { email, password } }),
  verifyMfa: (code: string) => request<SessionPayload>('/api/auth/mfa/verify/', { method: 'POST', body: { code } }),
  /** Where the browser goes to sign in through the organization of this email, or through one of the signed-in
   * person's organizations (spec 7.2); the provider's page is asked for the interface's language. */
  /** Spec 7.2, from the email: whether its domain's organization signs people in through a provider. */
  discoverSso: (email: string) =>
    request<{ available: boolean }>('/api/auth/sso/discover/', { method: 'POST', body: { email } }),
  startSso: (target: { email: string } | { organization: number }, language: string) =>
    request<{ redirect: string }>('/api/auth/sso/start/', { method: 'POST', body: { ...target, language } }),
  logout: () => request<void>('/api/auth/logout/', { method: 'POST' }),
  switchOrganization: (organizationId: number) =>
    request<SessionPayload>('/api/auth/switch-organization/', { method: 'POST', body: { organization_id: organizationId } }),
}
