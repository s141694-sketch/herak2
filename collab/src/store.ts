import type { Rows } from '@harak2/shared'

/** What the collaboration service needs from Django. A fake implements it in tests. */
export interface LoadedDocument {
  version_id: number
  editable: boolean
  level_count: number
  state: string | null
  rows: Pick<Rows, 'nodes' | 'blocks' | 'links'> | null
}

export type SaveResult = { status: 'saved' } | { status: 'locked' } | { status: 'failed'; error: string }

export interface DocumentStore {
  load(versionId: number): Promise<LoadedDocument>
  save(versionId: number, state: Uint8Array, rows: Rows, actorId: string | null): Promise<SaveResult>
  reportFailure(versionId: number, error: string): Promise<void>
}

const toBase64 = (bytes: Uint8Array) => Buffer.from(bytes).toString('base64')

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

  async save(versionId: number, state: Uint8Array, rows: Rows, actorId: string | null): Promise<SaveResult> {
    const response = await this.call('PUT', `/api/internal/collab/documents/${versionId}/`, {
      state: toBase64(state),
      rows,
      actor_id: actorId,
    })
    if (response.ok) return { status: 'saved' }
    const body = (await response.json().catch(() => ({}))) as { error?: { code?: string; message?: string } }
    if (response.status === 409 && body.error?.code === 'version_locked') return { status: 'locked' }
    return { status: 'failed', error: body.error?.message ?? `HTTP ${response.status}` }
  }

  async reportFailure(versionId: number, error: string): Promise<void> {
    await this.call('POST', `/api/internal/collab/documents/${versionId}/failure/`, { error })
  }
}
