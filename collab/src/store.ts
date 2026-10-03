import type { Rows } from '@harak2/shared'

/** What the collaboration service needs from Django. A fake implements it in tests. */
export interface LoadedDocument {
  version_id: number
  editable: boolean
  level_count: number
  state: string | null
  rows: Pick<Rows, 'nodes' | 'blocks' | 'links'> | null
}

export type SaveResult =
  | { status: 'saved'; stale?: boolean }
  | { status: 'locked' }
  /**
   * `stateSaved`: Django stored the state though it refused the rows, so the content is safe there.
   * `retryable`: the failure may pass by itself (Django unreachable or overloaded), so the save is tried again.
   */
  | { status: 'failed'; error: string; code: string; stateSaved: boolean; retryable: boolean }

export interface DocumentStore {
  load(versionId: number): Promise<LoadedDocument>
  /** `seq` grows with every save of the service; Django ignores a save older than the one it holds. */
  save(versionId: number, state: Uint8Array, rows: Rows, actorId: string | null, seq: number): Promise<SaveResult>
  reportFailure(versionId: number, error: string, code: string): Promise<void>
}

const toBase64 = (bytes: Uint8Array) => Buffer.from(bytes).toString('base64')

interface ErrorBody {
  error?: { code?: string; message?: string; details?: { state_saved?: boolean } | null }
}

/** Calls the internal Django endpoints with the shared service secret. */
export class DjangoStore implements DocumentStore {
  constructor(
    private readonly baseUrl: string,
    private readonly secret: string,
    private readonly timeoutMs = 10_000,
  ) {}

  private async call(method: string, path: string, body?: unknown): Promise<Response> {
    return fetch(`${this.baseUrl}${path}`, {
      method,
      headers: { Authorization: `Service ${this.secret}`, 'Content-Type': 'application/json', Accept: 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(this.timeoutMs),
    })
  }

  async load(versionId: number): Promise<LoadedDocument> {
    const response = await this.call('GET', `/api/internal/collab/documents/${versionId}/`)
    if (!response.ok) throw new Error(`load ${versionId}: HTTP ${response.status}`)
    return (await response.json()) as LoadedDocument
  }

  async save(versionId: number, state: Uint8Array, rows: Rows, actorId: string | null, seq: number): Promise<SaveResult> {
    let response: Response
    try {
      response = await this.call('PUT', `/api/internal/collab/documents/${versionId}/`, {
        state: toBase64(state),
        rows,
        actor_id: actorId,
        seq,
      })
    } catch (error) {
      return { status: 'failed', error: (error as Error).message, code: 'save_unavailable', stateSaved: false, retryable: true }
    }
    const body = (await response.json().catch(() => ({}))) as ErrorBody & { stale?: boolean }
    if (response.ok) return { status: 'saved', stale: Boolean(body.stale) }
    const error = body.error?.message ?? `HTTP ${response.status}`
    if (response.status === 409 && body.error?.code === 'version_locked') return { status: 'locked' }
    if (response.status === 422) {
      const stateSaved = body.error?.details?.state_saved === true
      return { status: 'failed', error, code: body.error?.code ?? 'rows_invalid', stateSaved, retryable: false }
    }
    if (response.status === 413) {
      return { status: 'failed', error, code: 'document_too_large', stateSaved: false, retryable: false }
    }
    // Django down, overloaded or misconfigured: the edits stay here and the save is tried again.
    const retryable = response.status >= 500 || response.status === 429 || response.status === 401 || response.status === 403
    return { status: 'failed', error, code: retryable ? 'save_unavailable' : 'save_refused', stateSaved: false, retryable }
  }

  async reportFailure(versionId: number, error: string, code: string): Promise<void> {
    await this.call('POST', `/api/internal/collab/documents/${versionId}/failure/`, { error, code })
  }
}
