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
