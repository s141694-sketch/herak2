import type { Rows } from '@harak2/shared'

import type { DocumentStore, LoadedDocument, SaveResult } from '../src/store'

/** An in-memory Django: rows and state per version, with switches to simulate locks and failures. */
export class FakeStore implements DocumentStore {
  documents = new Map<number, LoadedDocument>()
  saves: Array<{ versionId: number; rows: Rows; actorId: string | null }> = []
  failures: Array<{ versionId: number; error: string }> = []
  nextSave: SaveResult = { status: 'saved' }

  seed(versionId: number, doc: Partial<LoadedDocument>) {
    this.documents.set(versionId, { version_id: versionId, editable: true, level_count: 4, state: null, rows: null, ...doc })
  }

  async load(versionId: number): Promise<LoadedDocument> {
    const doc = this.documents.get(versionId)
    if (!doc) throw new Error('not found')
    return doc
  }

  async save(versionId: number, state: Uint8Array, rows: Rows, actorId: string | null): Promise<SaveResult> {
    const result = this.nextSave
    if (result.status === 'saved') {
      this.saves.push({ versionId, rows, actorId })
      this.documents.get(versionId)!.state = Buffer.from(state).toString('base64')
    }
    return result
  }

  async reportFailure(versionId: number, error: string) {
    this.failures.push({ versionId, error })
  }
}
