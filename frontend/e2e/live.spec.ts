import { type Browser, expect, type Page, test } from '@playwright/test'

// Phase 3: two people edit one draft live; submission locks it for both.
const PASSWORD = process.env.E2E_PASSWORD ?? 'harak-e2e-password'

async function signIn(browser: Browser, email: string): Promise<Page> {
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

async function api<T>(page: Page, method: string, path: string, body?: unknown): Promise<T> {
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

/** A fresh program owned by the admin with the author added as an editor; returns the draft's version id. */
async function freshProgram(admin: Page): Promise<number> {
  const stamp = Date.now().toString().slice(-6)
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
  return program.versions[0].id
}

/** The editor's text without other people's caret labels, which are drawn inside it. */
function textOf(editor: ReturnType<Page['locator']>) {
  return editor.evaluate((element) => {
    const clone = element.cloneNode(true) as HTMLElement
    clone.querySelectorAll('.collaboration-carets__caret').forEach((caret) => caret.remove())
    return clone.textContent
  })
}

async function openLive(page: Page, versionId: number) {
  await page.goto(`/program-versions/${versionId}`)
  await expect(page.getByTestId('live-status')).toHaveAttribute('data-mode', 'write')
  await expect(page.getByTestId('live-status')).toHaveAttribute('data-state', 'connected')
}

test('two editors see each other live, and submission locks the draft for both', async ({ browser }) => {
  test.setTimeout(90_000)
  const admin = await signIn(browser, 'multi@example.com')
  const author = await signIn(browser, 'author@example.com')
  const versionId = await freshProgram(admin)
  await openLive(admin, versionId)
  await openLive(author, versionId)

  // Structure added by one appears for the other.
  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).fill('الوحدة المشتركة')
  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).press('Enter')
  await expect(author.getByTestId('node-الوحدة المشتركة')).toBeVisible()
  await author.getByTestId('add-block-الوحدة المشتركة').getByRole('button').click()
  await expect(admin.getByTestId('block-objective')).toBeVisible()

  // Both type Arabic into the same block; both end with the same text.
  const adminEditor = admin.getByTestId('block-objective').locator('.ProseMirror')
  const authorEditor = author.getByTestId('block-objective').locator('.ProseMirror')
  await expect(author.getByTestId('presence-here')).toContainText('مازن القنوبي')
  await adminEditor.click()
  await admin.keyboard.type('يصف المتدرب')
  await expect.poll(() => textOf(authorEditor)).toBe('يصف المتدرب')
  // Presence: the author sees who is editing this block, and the admin's named caret inside it.
  await expect(author.getByTestId('block-objective').getByTestId('block-presence')).toHaveText('مازن القنوبي يحرر هنا')
  await expect(author.getByTestId('block-objective').locator('.collaboration-carets__label')).toHaveText('مازن القنوبي')
  await author.screenshot({ path: 'e2e/screenshots/20-presence-ar.png', fullPage: true })
  await authorEditor.click()
  await author.keyboard.press('End')
  await author.keyboard.type(' خطوات الإجراء')
  await expect.poll(() => textOf(adminEditor)).toBe('يصف المتدرب خطوات الإجراء')

  // Submission by one locks the editor of the other, which says so.
  await admin.getByTestId('submit-version').click()
  await expect(author.getByTestId('live-status')).toHaveAttribute('data-state', 'locked')
  await expect(authorEditor).toHaveAttribute('contenteditable', 'false')

  // The submitted rows hold what both typed.
  const tree = await api<{ blocks: Array<{ content: unknown }> }>(admin, 'GET', `/api/program-versions/${versionId}/tree/`)
  expect(JSON.stringify(tree.blocks[0].content)).toContain('يصف المتدرب خطوات الإجراء')
})
