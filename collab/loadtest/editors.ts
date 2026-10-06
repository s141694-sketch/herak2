/**
 * Light load test, part (a) (task 8.2, spec 8.3, D82): several editors on one live document, through the real
 * collaboration service and the real backend. Each editor types into its own block at a steady rate; every edit
 * carries the moment it was made, and every other editor records how long it took to arrive. At the end the
 * editors must agree, and the rows the backend saved must hold what they typed.
 *
 *   npx tsx collab/loadtest/editors.ts            (from the repository's root; settings below, from the environment)
 *
 * API (http://127.0.0.1:8000), COLLAB (ws://127.0.0.1:1234), COLLAB_TOKEN_SECRET (development's), EDITORS (10),
 * SECONDS (120), RATE (edits a second per editor, 2), EMAIL and PASSWORD (the e2e seed's admin), OUT (a JSON file).
 * Tokens are signed here with the service's secret, so the test runs past their usual two minutes.
 */
import { writeFileSync } from 'node:fs'

import { addBlock, addNode, blockFragment, blocksOf, setBlockContent, textsOf } from '@harak2/shared'
import { HocuspocusProvider, HocuspocusProviderWebsocket } from '@hocuspocus/provider'
import { SignJWT } from 'jose'
import WebSocket from 'ws'
import * as Y from 'yjs'

const env = process.env
const API = env.API ?? 'http://127.0.0.1:8000'
const COLLAB = env.COLLAB ?? 'ws://127.0.0.1:1234'
const SECRET = env.COLLAB_TOKEN_SECRET ?? 'dev-only-collab-token-secret-change-me'
const EDITORS = Number(env.EDITORS ?? 10)
const SECONDS = Number(env.SECONDS ?? 120)
const RATE = Number(env.RATE ?? 2)
const EMAIL = env.EMAIL ?? 'multi@example.com'
const PASSWORD = env.PASSWORD ?? env.E2E_PASSWORD ?? 'harak-e2e-password'

// --- The backend, as a signed-in admin -------------------------------------------------------------------------

const cookies = new Map<string, string>()
async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Referer: `${API}/` }
  if (cookies.has('csrftoken')) headers['X-CSRFToken'] = cookies.get('csrftoken')!
  headers.Cookie = [...cookies].map(([k, v]) => `${k}=${v}`).join('; ')
  const response = await fetch(API + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  for (const line of response.headers.getSetCookie()) {
    const [pair] = line.split(';')
    const at = pair.indexOf('=')
    cookies.set(pair.slice(0, at), pair.slice(at + 1))
  }
  if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`)
  return (response.status === 204 ? null : await response.json()) as T
}

interface Session {
  user: { id: number }
  organization: { id: number; slug: string } | null
  memberships: Array<{ organization: { id: number; slug: string } }>
}

async function setUp() {
  await api('GET', '/api/auth/csrf/')
  let session = await api<Session>('POST', '/api/auth/login/', { email: EMAIL, password: PASSWORD })
  if (session.organization?.slug !== 'vtc') {
    const vtc = session.memberships.find((m) => m.organization.slug === 'vtc')!.organization
    session = await api<Session>('POST', '/api/auth/switch-organization/', { organization_id: vtc.id })
  }
  const stamp = `${Date.now()}`.slice(-6)
  const levels = [{ name_ar: 'وحدة', name_en: 'Module' }]
  const template = await api<{ versions: Array<{ id: number }> }>('POST', '/api/structure-templates/', { name: `حمل ${stamp}`, levels })
  await api('POST', `/api/template-versions/${template.versions[0].id}/publish/`)
  const framework = await api<{ versions: Array<{ id: number }> }>('POST', '/api/competency-frameworks/', { name: `حمل ${stamp}` })
  await api('POST', `/api/framework-versions/${framework.versions[0].id}/competencies/`, { code: 'L-1', title: 'كفاية' })
  await api('POST', `/api/framework-versions/${framework.versions[0].id}/publish/`)
  const program = await api<{ versions: Array<{ id: number }> }>('POST', '/api/programs/', {
    title: `اختبار الحمل ${stamp}`,
    target_role: 'فني',
    template_version: template.versions[0].id,
    framework_version: framework.versions[0].id,
    targets: [],
  })
  return { userId: session.user.id, organization: session.organization!.id, version: program.versions[0].id }
}

// --- The editors -----------------------------------------------------------------------------------------------

interface Editor {
  index: number
  doc: Y.Doc
  provider: HocuspocusProvider
  socket: HocuspocusProviderWebsocket
  disconnects: number
}

async function token(user: number, organization: number, version: number, name: string) {
  const now = Math.floor(Date.now() / 1000)
  return new SignJWT({ sub: String(user), org: organization, ver: version, doc: `program-version:${version}`, mode: 'write', name })
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuer('harak2-api')
    .setAudience('harak2-collab')
    .setIssuedAt(now)
    .setExpirationTime(now + SECONDS + 600)
    .sign(new TextEncoder().encode(SECRET))
}

function connect(index: number, name: string, value: string): Promise<Editor> {
  return new Promise((resolve, reject) => {
    const doc = new Y.Doc()
    const socket = new HocuspocusProviderWebsocket({ url: COLLAB, WebSocketPolyfill: WebSocket })
    const editor = { index, doc, socket, disconnects: 0 } as Editor
    editor.provider = new HocuspocusProvider({
      name,
      document: doc,
      token: value,
      websocketProvider: socket,
      onSynced: () => resolve(editor),
      onDisconnect: () => {
        editor.disconnects += 1
      },
      onAuthenticationFailed: ({ reason }) => reject(new Error(reason)),
    })
    editor.provider.attach()
  })
}

const pingsOf = (doc: Y.Doc) => doc.getMap<number>('loadtest')
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

function percentile(sorted: number[], p: number) {
  return sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))] : null
}

function textsByBlock(doc: Y.Doc): Record<string, string> {
  const out: Record<string, string> = {}
  blocksOf(doc).forEach((_, key) => {
    out[key] = textsOf(blockFragment(doc, key)).map((t) => t.toString()).join('\n')
  })
  return out
}

function textOfContent(content: unknown): string {
  if (!content || typeof content !== 'object') return ''
  const node = content as { text?: string; content?: unknown[] }
  return (node.text ?? '') + (node.content ?? []).map(textOfContent).join('')
}

async function main() {
  const { userId, organization, version } = await setUp()
  const name = `program-version:${version}`
  const editors: Editor[] = []
  for (let i = 0; i < EDITORS; i += 1) editors.push(await connect(i, name, await token(userId, organization, version, `محرر ${i + 1}`)))

  // The first editor lays out a unit with one block for each editor; all wait to see them.
  const first = editors[0]
  const unit = addNode(first.doc, { parent: null, title: 'وحدة اختبار الحمل' }, 1)
  const blocks = editors.map(() => addBlock(first.doc, { node_key: unit, type: 'content' }))
  blocks.forEach((key, i) =>
    setBlockContent(first.doc, key, { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: `المحرر ${i + 1}: ` }] }] }),
  )
  const started = Date.now()
  while (editors.some((e) => blocks.some((key) => !blocksOf(e.doc).has(key) || !textsOf(blockFragment(e.doc, key)).length))) {
    if (Date.now() - started > 30_000) throw new Error('the editors did not all receive the layout')
    await wait(50)
  }

  // Each edit records when it was made; the others record when it arrived.
  const latencies: number[] = []
  for (const editor of editors) {
    pingsOf(editor.doc).observe((event) => {
      if (event.transaction.local) return
      const now = Date.now()
      for (const key of event.keysChanged) latencies.push(now - (pingsOf(editor.doc).get(key) ?? now))
    })
  }
  let sent = 0
  const end = Date.now() + SECONDS * 1000
  const timers = editors.map((editor) =>
    setInterval(() => {
      if (Date.now() > end) return
      const text = textsOf(blockFragment(editor.doc, blocks[editor.index]))[0]
      editor.doc.transact(() => {
        text.insert(text.length, `كلمة${sent % 100} `)
        pingsOf(editor.doc).set(`${editor.index}:${sent}`, Date.now())
      })
      sent += 1
    }, 1000 / RATE),
  )
  await wait(SECONDS * 1000 + 200)
  timers.forEach(clearInterval)

  // The editors agree, then the saved rows hold what they typed.
  const stopped = Date.now()
  const reference = () => JSON.stringify(textsByBlock(editors[0].doc))
  while (editors.some((e) => JSON.stringify(textsByBlock(e.doc)) !== reference())) {
    if (Date.now() - stopped > 30_000) break
    await wait(50)
  }
  const converged = editors.every((e) => JSON.stringify(textsByBlock(e.doc)) === reference())
  const convergenceMs = Date.now() - stopped
  const live = textsByBlock(first.doc)
  let saved = false
  const savingStarted = Date.now()
  while (!saved && Date.now() - savingStarted < 30_000) {
    await api('GET', `/api/program-versions/${version}/diff/${version}/`) // a snapshot of the live document
    const tree = await api<{ blocks: Array<{ block_key: string; content: unknown }> }>('GET', `/api/program-versions/${version}/tree/`)
    const rows = Object.fromEntries(tree.blocks.map((b) => [b.block_key, textOfContent(b.content)]))
    saved = blocks.every((key) => (rows[key] ?? '').replace(/\n/g, '') === live[key].replace(/\n/g, ''))
    if (!saved) await wait(1000)
  }

  latencies.sort((a, b) => a - b)
  const report = {
    editors: EDITORS,
    seconds: SECONDS,
    rate_per_editor: RATE,
    edits_sent: sent,
    deliveries: latencies.length,
    expected_deliveries: sent * (EDITORS - 1),
    latency_ms: {
      p50: percentile(latencies, 50),
      p95: percentile(latencies, 95),
      p99: percentile(latencies, 99),
      max: latencies[latencies.length - 1] ?? null,
    },
    converged,
    convergence_ms: convergenceMs,
    saved_rows_match: saved,
    disconnects: editors.reduce((n, e) => n + e.disconnects, 0),
    characters_per_block: Math.round(Object.values(live).reduce((n, t) => n + t.length, 0) / blocks.length),
  }
  console.log(JSON.stringify(report, null, 2))
  if (env.OUT) writeFileSync(env.OUT, JSON.stringify(report, null, 2))
  for (const editor of editors) {
    editor.provider.destroy()
    editor.socket.destroy()
  }
  process.exit(report.converged && report.saved_rows_match ? 0 : 1)
}

main().catch((error) => {
  console.error(error)
  process.exit(2)
})
