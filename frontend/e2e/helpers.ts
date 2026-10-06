import { createHmac } from 'node:crypto'
import { inflateRawSync } from 'node:zlib'

import { type Browser, expect, type Locator, type Page } from '@playwright/test'

export const PASSWORD = process.env.E2E_PASSWORD ?? 'harak-e2e-password'

export async function signIn(browser: Browser, email: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage()
  await page.goto('/login')
  await page.locator('input[name="email"]').fill(email)
  await page.locator('input[name="password"]').fill(PASSWORD)
  await page.locator('button[type="submit"]').click()
  await expect(page.getByTestId('home').or(page.getByTestId('choose-organization'))).toBeVisible()
  const switcher = page.getByTestId('organization-switcher')
  if (await switcher.isVisible()) await switcher.selectOption({ label: 'مركز التدريب المهني' })
  await expect(page.getByTestId('current-organization')).toHaveText('مركز التدريب المهني')
  return page
}

export async function api<T>(page: Page, method: string, path: string, body?: unknown): Promise<T> {
  return page.evaluate(
    async ({ method, path, body }) => {
      await fetch('/api/auth/csrf/')
      const token = decodeURIComponent(document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? '')
      const response = await fetch(path, {
        method,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`)
      return response.status === 204 ? null : response.json()
    },
    { method, path, body },
  ) as Promise<T>
}

/** A fresh program owned by the admin with the author added as an editor; returns ids of the program and its draft. */
export async function freshProgram(admin: Page): Promise<{ programId: number; versionId: number }> {
  const stamp = `${Date.now()}`.slice(-6)
  const levels = [
    { name_ar: 'وحدة', name_en: 'Module' },
    { name_ar: 'درس', name_en: 'Lesson' },
  ]
  const template = await api<{ versions: Array<{ id: number }> }>(admin, 'POST', '/api/structure-templates/', { name: `قالب ${stamp}`, levels })
  await api(admin, 'POST', `/api/template-versions/${template.versions[0].id}/publish/`)
  const framework = await api<{ versions: Array<{ id: number }> }>(admin, 'POST', '/api/competency-frameworks/', { name: `إطار ${stamp}` })
  const frameworkVersion = framework.versions[0].id
  await api(admin, 'POST', `/api/framework-versions/${frameworkVersion}/competencies/`, { code: 'C-1', title: 'كفاية' })
  await api(admin, 'POST', `/api/framework-versions/${frameworkVersion}/publish/`)
  const program = await api<{ id: number; versions: Array<{ id: number }> }>(admin, 'POST', '/api/programs/', {
    title: `برنامج حي ${stamp}`,
    target_role: 'فني',
    template_version: template.versions[0].id,
    framework_version: frameworkVersion,
    targets: [],
  })
  await api(admin, 'POST', `/api/programs/${program.id}/collaborators/`, { user_email: 'author@example.com' })
  return { programId: program.id, versionId: program.versions[0].id }
}

export async function openLive(page: Page, versionId: number, mode: 'read' | 'write' = 'write') {
  await page.goto(`/program-versions/${versionId}`)
  await expect(page.getByTestId('live-status')).toHaveAttribute('data-mode', mode)
  await expect(page.getByTestId('live-status')).toHaveAttribute('data-state', 'connected')
  // Connected is not synced: the tree (and its block editors) appear after the first sync.
  await expect(page.getByTestId('tree')).toBeVisible()
}

/** The editor's text without other people's caret labels, which are drawn inside it. */
export function textOf(editor: Locator) {
  return editor.evaluate((element) => {
    const clone = element.cloneNode(true) as HTMLElement
    clone.querySelectorAll('.collaboration-carets__caret').forEach((caret) => caret.remove())
    return clone.textContent
  })
}

/** Runs a TipTap command on the editor of the first block of a type (positions are document positions). */
export async function inEditor(page: Page, blockType: string, script: string, args: Record<string, unknown> = {}) {
  return page.evaluate(
    ({ blockType, script, args }) => {
      const element = document.querySelector(`[data-testid="block-${blockType}"] .ProseMirror`) as HTMLElement & { editor: any }
      // eslint-disable-next-line @typescript-eslint/no-implied-eval
      return new Function('editor', 'args', script)(element.editor, args)
    },
    { blockType, script, args },
  )
}

/** Document positions of a quote inside a single-paragraph block (the paragraph starts at 1). */
export const RANGE_OF = `
  const text = editor.state.doc.textContent
  const index = text.indexOf(args.quote)
  if (index < 0) throw new Error('quote not found: ' + args.quote)
  return { from: 1 + index, to: 1 + index + args.quote.length }
`

/** Comments on a quote in the first objective block, through the selection button as a person would. */
export async function comment(page: Page, quote: string, body: string, category: 'must_fix' | 'suggestion') {
  await expect(page.getByTestId('block-objective').locator('.ProseMirror').first()).toBeVisible()
  const range = await inEditor(page, 'objective', RANGE_OF, { quote })
  await inEditor(page, 'objective', 'editor.commands.setTextSelection(args)', range)
  await page.getByTestId('block-objective').getByTestId('comment-selection').click()
  await expect(page.getByTestId('new-comment')).toContainText(quote)
  await page.getByTestId('comment-category').selectOption(category)
  await page.getByTestId('comment-body').fill(body)
  await page.getByTestId('comment-save').click()
}

export const card = (page: Page, text: string) => page.getByTestId('comment').filter({ hasText: text })

/** A TOTP code (RFC 6238: HMAC-SHA1, 30 s, 6 digits) for a base32 secret, ``steps`` time steps from now. */
export function totp(secret: string, steps = 0): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const char of secret.replace(/=+$/, '').toUpperCase()) bits += alphabet.indexOf(char).toString(2).padStart(5, '0')
  const key = Buffer.from(bits.match(/.{8}/g)!.map((byte) => parseInt(byte, 2)))
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 1000 / 30) + steps))
  const digest = createHmac('sha1', key).update(counter).digest()
  const offset = digest[digest.length - 1] & 0xf
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, '0')
}

/** Signs in on Keycloak's own page (the realms in infra/keycloak use one test password). */
export async function keycloakSignIn(page: Page, username: string) {
  await page.locator('input[name="username"]').fill(username)
  await page.locator('input[name="password"]').fill('harak-sso-test')
  await page.locator('#kc-login').click()
}

/** The text of a Word file's body, a paragraph a line: its word/document.xml read out of the zip. */
export function docxText(file: Buffer): string {
  const end = file.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]))
  if (end < 0) throw new Error('not a zip file')
  let entry = file.readUInt32LE(end + 16)
  for (let i = 0; i < file.readUInt16LE(end + 10); i += 1) {
    const method = file.readUInt16LE(entry + 10)
    const size = file.readUInt32LE(entry + 20)
    const nameLength = file.readUInt16LE(entry + 28)
    const name = file.toString('utf-8', entry + 46, entry + 46 + nameLength)
    if (name === 'word/document.xml') {
      const local = file.readUInt32LE(entry + 42)
      const start = local + 30 + file.readUInt16LE(local + 26) + file.readUInt16LE(local + 28)
      const data = file.subarray(start, start + size)
      const xml = (method === 8 ? inflateRawSync(data) : data).toString('utf-8')
      return xml
        .replace(/<w:p[ >]/g, '\n$&')
        .replace(/<[^>]+>/g, '')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&amp;/g, '&')
    }
    entry += 46 + nameLength + file.readUInt16LE(entry + 30) + file.readUInt16LE(entry + 32)
  }
  throw new Error('no word/document.xml')
}
