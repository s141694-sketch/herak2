import { readFileSync } from 'node:fs'

import { type Browser, expect, type Locator, type Page, test } from '@playwright/test'

import { docxText, PASSWORD } from './helpers'

// Task 8.1, spec 8.1 item 8: the whole journey through the browser, once in Arabic and once in English, with
// the interface in the journey's language from its first page: setup -> authoring -> submit -> review ->
// return -> resubmit -> approve -> export. Every step goes through the pages; the texts checked are read from
// the interface's own dictionaries, so the English run fails on any Arabic left in what it checks, and back.

type Language = 'ar' | 'en'
type Dictionary = Record<string, unknown>

const dictionaries: Record<Language, Dictionary> = {
  ar: JSON.parse(readFileSync(new URL('../src/i18n/ar.json', import.meta.url), 'utf-8')),
  en: JSON.parse(readFileSync(new URL('../src/i18n/en.json', import.meta.url), 'utf-8')),
}

function translator(language: Language) {
  return (key: string, values: Record<string, string | number> = {}) => {
    const text = key.split('.').reduce<unknown>((node, part) => (node as Dictionary)[part], dictionaries[language])
    if (typeof text !== 'string') throw new Error(`no text ${key} in ${language}`)
    return text.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(values[name]))
  }
}

const ORGANIZATION = 'مركز التدريب المهني'

/** A person signed in, in their own browser, with the interface in ``language`` before the first page. */
async function signIn(browser: Browser, email: string, language: Language): Promise<Page> {
  const context = await browser.newContext({
    storageState: { cookies: [], origins: [{ origin: 'http://localhost:5173', localStorage: [{ name: 'harak.language', value: language }] }] },
  })
  const page = await context.newPage()
  await page.goto('/login')
  await expect(page.locator('html')).toHaveAttribute('lang', language)
  await expect(page.locator('html')).toHaveAttribute('dir', language === 'ar' ? 'rtl' : 'ltr')
  await page.locator('input[name="email"]').fill(email)
  await page.locator('input[name="password"]').fill(PASSWORD)
  await page.locator('button[type="submit"]').click()
  await expect(page.getByTestId('home').or(page.getByTestId('choose-organization'))).toBeVisible()
  const switcher = page.getByTestId('organization-switcher')
  if (await switcher.isVisible()) await switcher.selectOption({ label: ORGANIZATION })
  await expect(page.getByTestId('current-organization')).toHaveText(ORGANIZATION)
  // The menus are in the journey's language only (names of people and organizations are data, not menus).
  await expect(page.getByRole('navigation')).not.toHaveText(language === 'ar' ? /[A-Za-z]/ : /[\u0600-\u06FF]/)
  return page
}

async function takeAndOpen(page: Page, title: string): Promise<Locator> {
  await page.goto('/tasks')
  const row = page.getByTestId('task-list').locator('li', { hasText: title })
  await row.getByTestId('task-claim').click()
  await expect(row.getByTestId('task-release')).toBeVisible()
  await row.getByTestId('task-open').click()
  return page.getByTestId('review-panel')
}

/** Submits the open draft, giving the reason the pre-submit check asks for when critical findings remain. */
async function submit(author: Page, reason: string) {
  await author.getByTestId('submit-version').click()
  const asked = author.getByTestId('submit-reason')
  await expect(author.getByTestId('review-panel').or(asked)).toBeVisible()
  if (await asked.isVisible()) {
    await expect(author.getByTestId('version-error')).toBeVisible()
    await asked.fill(reason)
    await author.getByTestId('submit-version').click()
  }
  await expect(author.getByTestId('review-panel')).toBeVisible()
  await expect(author.getByTestId('live-status')).toHaveAttribute('data-mode', 'read')
}

async function download(page: Page, link: Locator) {
  const [file] = await Promise.all([page.waitForEvent('download'), link.click()])
  const stream = await file.createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of stream) chunks.push(chunk as Buffer)
  return { name: file.suggestedFilename(), bytes: Buffer.concat(chunks) }
}

for (const language of ['ar', 'en'] as const) {
  test(`the whole journey in ${language === 'ar' ? 'Arabic' : 'English'}: setup to export`, async ({ browser }) => {
    test.setTimeout(240_000)
    const t = translator(language)
    const shot = (page: Page, step: string) => page.screenshot({ path: `e2e/screenshots/9${step}-journey-${language}.png`, fullPage: true })
    const stamp = `${Date.now()}`.slice(-6)
    const ar = language === 'ar'
    const names = {
      template: ar ? `قالب الرحلة ${stamp}` : `Journey template ${stamp}`,
      framework: ar ? `إطار الرحلة ${stamp}` : `Journey framework ${stamp}`,
      program: ar ? `برنامج الرحلة ${stamp}` : `Journey program ${stamp}`,
      module: ar ? 'الوحدة الأولى' : 'First module',
      objective: ar ? 'أن يحدد المتدرب مخاطر موقع العمل' : 'The trainee identifies the hazards of the work site',
      assessment: ar ? 'اختبار عملي في الموقع' : 'A practical test on site',
      reason: ar ? 'التقويم في النسخة التالية' : 'The assessment comes in the next version',
      mustFix: ar ? 'أضف تقويمًا يقيس الهدف' : 'Add an assessment that measures the objective',
      returnNote: ar ? 'ينقص التقويم' : 'The assessment is missing',
    }
    const level = (arName: string, enName: string) => (ar ? arName : enName)

    // 1. Setup: the admin defines a structure template, imports competencies, and creates the program.
    const admin = await signIn(browser, 'multi@example.com', language)
    await admin.getByTestId('nav-templates').click()
    await admin.getByTestId('template-name').fill(names.template)
    await admin.getByTestId('add-level').click()
    for (const [i, [arName, enName]] of [
      ['وحدة', 'Module'],
      ['درس', 'Lesson'],
    ].entries()) {
      await admin.getByTestId(`level-ar-${i}`).fill(arName)
      await admin.getByTestId(`level-en-${i}`).fill(enName)
    }
    await admin.getByTestId('create-template').click()
    await admin.getByTestId('publish-template').click()
    await expect(admin.getByTestId('template-levels').locator('li')).toHaveText([level('وحدة', 'Module'), level('درس', 'Lesson')])

    await admin.getByTestId('nav-competencies').click()
    await admin.getByTestId('framework-name').fill(names.framework)
    await admin.getByTestId('create-framework').click()
    const csv = ar
      ? 'الرمز,العنوان,المستوى,النوع\nJ-01,يحدد مخاطر موقع العمل,2,إلزامية\nJ-02,يستخدم معدات الوقاية,1,إلزامية\n'
      : 'code,title,level,type\nJ-01,Identifies the hazards of the work site,2,required\nJ-02,Uses protective equipment,1,required\n'
    await admin.getByTestId('import-file').setInputFiles({ name: 'competencies.csv', mimeType: 'text/csv', buffer: Buffer.from(csv, 'utf-8') })
    await admin.getByTestId('import-upload').click()
    await expect(admin.getByTestId('import-summary')).toHaveText(t('import.summary', { create: 2, update: 0, unchanged: 0, errors: 0 }))
    await admin.getByTestId('import-confirm').click()
    await expect(admin.getByTestId('competency-table').locator('tbody tr')).toHaveCount(2)
    await admin.getByTestId('publish-framework').click()
    await shot(admin, '0-framework')

    await admin.getByTestId('nav-programs').click()
    await admin.getByTestId('program-title').fill(names.program)
    await admin.getByTestId('program-role').fill(ar ? 'فني سلامة' : 'Safety technician')
    await admin.getByTestId('program-template').selectOption({ label: t('programs.templateOption', { name: names.template, number: 1 }) })
    await admin.getByTestId('program-framework').selectOption({ label: t('programs.templateOption', { name: names.framework, number: 1 }) })
    await admin.getByTestId('program-targets').getByRole('checkbox').nth(0).check()
    await admin.getByTestId('create-program').click()
    await expect(admin.getByTestId('program-heading')).toHaveText(names.program)
    const programUrl = admin.url()
    await admin.getByRole('textbox', { name: t('programs.collaboratorEmail') }).fill('author@example.com')
    await admin.getByRole('button', { name: t('programs.addCollaborator') }).click()
    await expect(admin.getByTestId('collaborators')).toContainText('author@example.com')
    await shot(admin, '1-program')

    // 2. Authoring: the author writes in the live editor and sees the quality report beside it.
    const author = await signIn(browser, 'author@example.com', language)
    await author.goto(programUrl)
    await author.getByRole('link', { name: t('common.version', { number: 1 }) }).click()
    await expect(author.getByTestId('live-status')).toHaveAttribute('data-state', 'connected')
    await expect(author.getByTestId('live-status')).toHaveAttribute('data-mode', 'write')
    const addModule = author.getByRole('textbox', { name: t('tree.addRoot', { level: level('وحدة', 'Module') }) })
    await addModule.fill(names.module)
    await addModule.press('Enter')
    await expect(author.getByTestId(`node-${names.module}`)).toBeVisible()
    const blocks = author.getByTestId(`add-block-${names.module}`)
    await blocks.locator('select').selectOption('objective')
    await blocks.getByRole('button').click()
    await author.getByTestId('block-objective').locator('.ProseMirror').click()
    await author.keyboard.type(names.objective)
    await author.getByTestId('link-objective_competency').selectOption({ index: 1 })
    await expect(author.getByTestId('block-objective').locator('.chip')).toContainText('J-01')
    await expect(author.getByTestId('quality-panel')).toBeVisible()
    await shot(author, '2-authoring')
    await submit(author, names.reason)

    // 3. Review: the reviewer takes the task, leaves a must-fix comment and returns the version.
    const reviewer = await signIn(browser, 'reviewer@example.com', language)
    let panel = await takeAndOpen(reviewer, names.program)
    await expect(panel).toContainText(t('workflow.review'))
    const objective = reviewer.getByTestId('block-objective')
    await objective.getByTestId('comment-selection').click()
    await reviewer.getByTestId('comment-category').selectOption('must_fix')
    await reviewer.getByTestId('comment-body').fill(names.mustFix)
    await reviewer.getByTestId('comment-save').click()
    await expect(objective.getByTestId('block-comments')).toContainText(names.mustFix)
    await panel.getByTestId('decision-note').fill(names.returnNote)
    await panel.getByTestId('decision-return').click()
    await expect(panel.getByTestId('review-outcome')).toContainText(t('workflow.outcome.returned'))
    await shot(reviewer, '3-returned')

    // 4. The author is told, fixes the new draft, resolves the comment and resubmits.
    await author.getByTestId('notifications-toggle').click()
    const told = author.getByTestId('notification').filter({ hasText: names.program }).first()
    await expect(told).toHaveAttribute('data-event', 'version_returned')
    await expect(told).toContainText(names.returnNote)
    await told.getByRole('button').click()
    await expect(author.getByTestId('program-heading')).toHaveText(names.program)
    await author.getByRole('link', { name: t('common.version', { number: 2 }) }).click()
    await expect(author.getByTestId('live-status')).toHaveAttribute('data-mode', 'write')
    await expect(author.getByTestId('returned-panel')).toContainText(names.returnNote)
    const moduleBlocks = author.getByTestId(`add-block-${names.module}`)
    await moduleBlocks.locator('select').selectOption('assessment')
    await moduleBlocks.getByRole('button').click()
    await author.getByTestId('block-assessment').locator('.ProseMirror').click()
    await author.keyboard.type(names.assessment)
    const mustFix = author.getByTestId('comment').filter({ hasText: names.mustFix })
    await mustFix.getByTestId('comment-resolve').click()
    await expect(mustFix).toHaveCount(0)
    await shot(author, '4-fixed')
    await submit(author, names.reason)

    // 5. The reviewer sees what was fixed and approves the stage; the approver approves the version.
    panel = await takeAndOpen(reviewer, names.program)
    await expect(panel.getByTestId('resolved-comment')).toContainText(names.mustFix)
    await panel.getByTestId('decision-approve').click()
    const approver = await signIn(browser, 'approver@example.com', language)
    panel = await takeAndOpen(approver, names.program)
    await panel.getByTestId('decision-note').fill(ar ? 'معتمد' : 'Approved')
    await panel.getByTestId('decision-approve').click()
    // Tasks run at once in these tests: the approval's request also makes the Word and PDF files.
    await expect(panel.getByTestId('review-outcome')).toHaveText(t('workflow.outcome.approved'), { timeout: 60_000 })
    await shot(approver, '5-approved')

    // 6. Export: the author downloads the Word and PDF files of the approved version.
    await author.reload()
    const exported = author.getByTestId('export-panel')
    await expect(exported).toHaveAttribute('data-status', 'done', { timeout: 60_000 })
    await expect(exported.getByRole('heading')).toHaveText(t('export.title'))
    const word = await download(author, exported.getByRole('link', { name: t('export.word') }))
    expect(word.name).toBe(`${names.program} - 2.docx`)
    expect(word.bytes.subarray(0, 2).toString()).toBe('PK')
    const lines = docxText(word.bytes).split('\n').filter((line) => line.trim())
    expect(lines).toEqual(expect.arrayContaining([names.program, names.module, names.objective, names.assessment]))
    const pdf = await download(author, exported.getByRole('link', { name: t('export.pdf') }))
    expect(pdf.bytes.subarray(0, 5).toString()).toBe('%PDF-')
    await shot(author, '6-exported')
  })
}
