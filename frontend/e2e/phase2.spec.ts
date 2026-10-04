import { expect, type Page, test } from '@playwright/test'

// Phase 2 completion criterion in the browser: a program on a four-level template, two versions,
// and a correct comparison between them. Names carry a stamp because the e2e database persists.
const PASSWORD = process.env.E2E_PASSWORD ?? 'harak-e2e-password'
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e/screenshots/${name}.png`, fullPage: true })

async function signInAsAdmin(page: Page) {
  await page.goto('/login')
  await page.locator('input[name="email"]').fill('multi@example.com')
  await page.locator('input[name="password"]').fill(PASSWORD)
  await page.locator('button[type="submit"]').click()
  // This user belongs to two organizations, so the header always offers the switcher.
  await page.getByTestId('organization-switcher').selectOption({ label: 'مركز التدريب المهني' })
  await expect(page.getByTestId('current-role')).toHaveText('مدير التدريب')
}

async function typeInto(page: Page, editor: ReturnType<Page['locator']>, text: string) {
  await editor.click()
  await page.keyboard.press('Control+a')
  await page.keyboard.type(text)
  // Drafts are live: every keystroke goes to the collaboration service, which saves rows on its own.
  await expect(editor).toHaveText(text)
}

async function expectLiveEditing(page: Page) {
  await expect(page.getByTestId('live-status')).toHaveAttribute('data-state', 'connected')
  await expect(page.getByTestId('live-status')).toHaveAttribute('data-mode', 'write')
}

test('a program on a four-level template, two versions, and a correct comparison', async ({ page }) => {
  test.setTimeout(120_000)
  const stamp = Date.now().toString().slice(-6)
  const templateName = `قالب البرامج ${stamp}`
  const frameworkName = `إطار السلامة ${stamp}`
  const programTitle = `برنامج السلامة المهنية ${stamp}`

  await signInAsAdmin(page)

  // 1. A structure template with four levels, published.
  await page.getByTestId('nav-templates').click()
  await page.getByTestId('template-name').fill(templateName)
  for (let i = 0; i < 3; i += 1) await page.getByTestId('add-level').click()
  const levels = [
    ['برنامج', 'Program'],
    ['وحدة', 'Module'],
    ['درس', 'Lesson'],
    ['نشاط', 'Activity'],
  ]
  for (const [i, [ar, en]] of levels.entries()) {
    await page.getByTestId(`level-ar-${i}`).fill(ar)
    await page.getByTestId(`level-en-${i}`).fill(en)
  }
  await page.getByTestId('create-template').click()
  await page.getByTestId('publish-template').click()
  await expect(page.getByTestId('template-levels').locator('li')).toHaveText(['برنامج', 'وحدة', 'درس', 'نشاط'])

  // 2. A competency framework imported from CSV with a preview, then published.
  await page.getByTestId('nav-competencies').click()
  await page.getByTestId('framework-name').fill(frameworkName)
  await page.getByTestId('create-framework').click()
  const csv = 'الرمز,العنوان,المستوى,النوع\nSAF-01,يحدد مخاطر موقع العمل,2,إلزامية\nSAF-02,يستخدم معدات الوقاية,1,إلزامية\nSAF-03,يبلّغ عن الحوادث,1,اختيارية\n'
  await page.getByTestId('import-file').setInputFiles({ name: 'competencies.csv', mimeType: 'text/csv', buffer: Buffer.from(csv, 'utf-8') })
  await page.getByTestId('import-upload').click()
  await expect(page.getByTestId('import-summary')).toContainText('جديد: 3')
  await expect(page.getByTestId('import-preview').locator('tbody tr')).toHaveCount(3)
  await shot(page, '10-import-preview-ar')
  await page.getByTestId('import-confirm').click()
  await expect(page.getByTestId('competency-table').locator('tbody tr')).toHaveCount(3)
  await page.getByTestId('publish-framework').click()
  await expect(page.getByTestId('framework-versions')).toContainText('منشورة')

  // 3. A program on that template and framework.
  await page.getByTestId('nav-programs').click()
  await page.getByTestId('program-title').fill(programTitle)
  await page.getByTestId('program-role').fill('فني سلامة')
  await page.getByTestId('program-template').selectOption({ label: `${templateName} — النسخة 1` })
  await page.getByTestId('program-framework').selectOption({ label: `${frameworkName} — النسخة 1` })
  await page.getByTestId('program-targets').getByRole('checkbox').nth(0).check()
  await page.getByTestId('program-targets').getByRole('checkbox').nth(1).check()
  await page.getByTestId('create-program').click()
  await expect(page.getByTestId('program-heading')).toHaveText(programTitle)
  await page.getByRole('link', { name: 'النسخة 1' }).click()
  await expectLiveEditing(page)

  // 4. A tree four levels deep, with blocks and an alignment link.
  for (const [label, title] of [
    ['إضافة برنامج', 'البرنامج'],
    ['إضافة وحدة', 'الوحدة الأولى'],
    ['إضافة درس', 'الدرس الأول'],
    ['إضافة نشاط', 'النشاط التطبيقي'],
  ]) {
    await page.getByRole('textbox', { name: label }).fill(title)
    await page.getByRole('textbox', { name: label }).press('Enter')
    await expect(page.getByTestId(`node-${title}`)).toBeVisible()
  }
  await expect(page.getByTestId('node-النشاط التطبيقي')).toHaveAttribute('data-level', '3')
  await expect(page.getByRole('textbox', { name: /^إضافة/ }).filter({ hasText: '' })).toHaveCount(4)

  const lessonBlocks = page.getByTestId('add-block-الدرس الأول')
  await lessonBlocks.locator('select').selectOption('objective')
  await lessonBlocks.getByRole('button').click()
  await typeInto(page, page.getByTestId('block-objective').locator('.ProseMirror'), 'يحدد المتدرب مخاطر موقع العمل')
  await lessonBlocks.locator('select').selectOption('content')
  await lessonBlocks.getByRole('button').click()
  await typeInto(page, page.getByTestId('block-content').locator('.ProseMirror'), 'النص الأول للمحتوى')
  await page.getByTestId('link-objective_competency').selectOption({ index: 1 })
  await expect(page.getByTestId('block-objective').locator('.chip')).toContainText('SAF-01')
  await shot(page, '11-version-1-tree-ar')

  // 5. Submit, withdraw: version 1 is locked and version 2 is a draft copy.
  await page.getByTestId('submit-version').click()
  // A targeted competency without an assessment is a critical finding: the submission needs a reason (task 5.4).
  await page.getByTestId('submit-reason').fill('التقويم يُضاف في النسخة التالية')
  await page.getByTestId('submit-version').click()
  // The submitted version reopens read-only on its frozen live state.
  await expect(page.getByTestId('live-status')).toHaveAttribute('data-mode', 'read')
  await page.getByTestId('withdraw-version').click()
  await expect(page.getByTestId('program-versions').locator('tr')).toHaveCount(2)
  await expect(page.getByTestId('program-versions').locator('tr[data-version="1"]')).toContainText('مسحوبة')
  await expect(page.getByTestId('program-versions').locator('tr[data-version="2"]')).toContainText('مسودة')

  // 6. Change version 2: one block edited, one node renamed, one node added.
  await page.getByRole('link', { name: 'النسخة 2' }).click()
  await expectLiveEditing(page)
  await expect(page.getByTestId('block-content').locator('.ProseMirror')).toHaveText('النص الأول للمحتوى')
  await typeInto(page, page.getByTestId('block-content').locator('.ProseMirror'), 'النص المعدّل للمحتوى')
  const module = page.getByTestId('node-الوحدة الأولى')
  await module.locator('.node-header').first().getByTestId('rename-node').click()
  await module.getByTestId('rename-input').fill('الوحدة الأولى المعدّلة')
  await module.getByTestId('rename-input').press('Enter')
  await expect(page.getByTestId('node-الوحدة الأولى المعدّلة')).toBeVisible()
  await page.getByRole('textbox', { name: 'إضافة وحدة' }).fill('الوحدة الثانية')
  await page.getByRole('textbox', { name: 'إضافة وحدة' }).press('Enter')
  await expect(page.getByTestId('node-الوحدة الثانية')).toBeVisible()

  // 7. Compare version 1 with version 2.
  await page.getByRole('link', { name: programTitle }).click()
  await page.getByTestId('compare-from').selectOption({ label: 'النسخة 1' })
  await page.getByTestId('compare-to').selectOption({ label: 'النسخة 2' })
  await page.getByTestId('compare-go').click()
  await expect(page.getByTestId('diff-nodes-summary')).toHaveText('مضاف: 1 · محذوف: 0 · معدّل: 1 · منقول: 0 · بلا تغيير: 3')
  await expect(page.getByTestId('diff-blocks-summary')).toHaveText('مضاف: 0 · محذوف: 0 · معدّل: 1 · منقول: 0 · بلا تغيير: 1')
  await expect(page.locator('.removed-text')).toContainText('النص الأول للمحتوى')
  await expect(page.locator('.added-text')).toContainText('النص المعدّل للمحتوى')
  await shot(page, '12-diff-ar')

  await page.getByTestId('language-toggle').click()
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr')
  await expect(page.getByTestId('diff-nodes-summary')).toHaveText('Added: 1 · Removed: 0 · Modified: 1 · Moved: 0 · Unchanged: 3')
  await expect(page.getByRole('heading', { name: 'Comparing version 1 with version 2' })).toBeVisible()
  await shot(page, '13-diff-en')
})
