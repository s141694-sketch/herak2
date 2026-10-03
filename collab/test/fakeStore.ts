import type { Rows } from '@harak2/shared'

import type { DocumentStore, LoadedDocument, SaveResult } from '../src/store'

/** An in-memory Django: rows and state per version, with switches to simulate locks, failures and slowness. */
export class FakeStore implements DocumentStore {
  documents = new Map<number, LoadedDocument>()
  saves: Array<{ versionId: number; rows: Rows; actorId: string | null; seq: number }> = []
  attempts = 0
  failures: Array<{ versionId: number; error: string; code: string }> = []
  /** What the next saves answer; 'throw' simulates Django being unreachable. */
  nextSave: SaveResult | 'throw' = { status: 'saved' }
  loadDelayMs = 0
  loads = 0

  seed(versionId: number, doc: Partial<LoadedDocument>) {
    this.documents.set(versionId, { version_id: versionId, editable: true, level_count: 4, state: null, rows: null, ...doc })
  }

  async load(versionId: number): Promise<LoadedDocument> {
    this.loads += 1
    if (this.loadDelayMs) await new Promise((r) => setTimeout(r, this.loadDelayMs))
    const doc = this.documents.get(versionId)
    if (!doc) throw new Error('not found')
    return { ...doc }
  }

  async save(versionId: number, state: Uint8Array, rows: Rows, actorId: string | null, seq: number): Promise<SaveResult> {
    this.attempts += 1
    const result = this.nextSave
    if (result === 'throw') throw new Error('connect ECONNREFUSED')
    if (result.status === 'saved' || (result.status === 'failed' && result.stateSaved)) {
      this.documents.get(versionId)!.state = Buffer.from(state).toString('base64')
    }
    if (result.status === 'saved') this.saves.push({ versionId, rows, actorId, seq })
    return result
  }

  async reportFailure(versionId: number, error: string, code: string) {
    this.failures.push({ versionId, error, code })
  }
}
