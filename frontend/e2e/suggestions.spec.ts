import { expect, type Page, type Request, test } from '@playwright/test'

import { api, freshProgram, inEditor, openLive, signIn, textOf } from './helpers'

// Task 4.8: the drafting agent suggests, the author decides. No model is reachable here, so the real request path
// is checked for what it answers without one, and ready suggestions are served by route mocks to check that
// accepting writes them into the live document (seen by the other editor) and that both decisions are sent.

const WEAK = 'أن يفهم المتدرب أهمية الإسعافات'
const SOUND = 'أن يقدم المتدرب الإسعافات الأولية لمصاب بنزيف وفق دليل الإسعاف خلال دقيقتين'

async function draftWithObjective(admin: Page, author: Page, text: string) {
  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).fill('الوحدة')
  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).press('Enter')
  await admin.getByTestId('add-block-الوحدة').getByRole('button').click()
  await admin.getByTestId('block-objective').locator('.ProseMirror').click()
  await admin.keyboard.type(text)
  await expect.poll(() => textOf(author.getByTestId('block-objective').locator('.ProseMirror'))).toBe(text)
}

/** Serves one suggestion through its life: the request, the polls, the list it is in once asked for, and the
 * decision. Returns the decisions sent. */
async function mockSuggestion(page: Page, ready: Record<string, unknown>) {
  const decisions: Array<{ decision: string; body: unknown }> = []
  const me = await api<{ user: { id: number } }>(page, 'GET', '/api/auth/me/')
  const base = { id: 901, version: 0, subject: '', reason: '', model: 'claude-opus-5-5', prompt_version: 't', requested_by: me.user, created_at: '', decided_at: null, decision_reason: '' }
  let asked = false
  await page.route(/\/api\/program-versions\/\d+\/suggestions\/$/, (route) => {
    if (route.request().method() === 'POST') {
      asked = true
      return route.fulfill({ status: 202, json: { ...base, ...ready, status: 'pending', result: null } })
    }
    return asked && !decisions.length ? route.fulfill({ json: [{ ...base, ...ready, status: 'ready' }] }) : route.fallback()
  })
  await page.route(/\/api\/suggestions\/901\/$/, (route) => route.fulfill({ json: { ...base, ...ready, status: 'ready' } }))
  await page.route(/\/api\/suggestions\/901\/(accept|dismiss)\/$/, (route) => {
    const request: Request = route.request()
    const decision = request.url().includes('/accept/') ? 'accepted' : 'dismissed'
    decisions.push({ decision, body: request.postDataJSON() })
    return route.fulfill({ json: { ...base, ...ready, status: decision } })
  })
  return decisions
}

test('without a model the request is answered plainly, and a sound objective is not sent', async ({ browser }) => {
  test.setTimeout(90_000)
  const admin = await signIn(browser, 'multi@example.com')
  const author = await signIn(browser, 'author@example.com')
  const { versionId } = await freshProgram(admin)
  await openLive(admin, versionId)
  await openLive(author, versionId)
  await draftWithObjective(admin, author, WEAK)

  await author.getByTestId('suggest-rewrite').click()
  await expect(author.getByTestId('suggestion-outcome')).toHaveAttribute('data-status', 'failed')
  await expect(author.getByTestId('suggestion-outcome')).toContainText('الذكاء الاصطناعي غير مُعدّ على هذا الخادم')
  const listed = await api<Array<{ status: string; reason: string; original: string }>>(admin, 'GET', `/api/program-versions/${versionId}/suggestions/`)
  expect(listed).toEqual([expect.objectContaining({ status: 'failed', reason: 'not_configured', original: WEAK })])

  await author.getByTestId('suggestion-outcome').getByRole('button').click()
  const all = await inEditor(author, 'objective', 'return editor.state.doc.content.size')
  await inEditor(author, 'objective', `editor.chain().focus().deleteRange({ from: 1, to: ${Number(all) - 1} }).insertContent(args.text).run()`, { text: SOUND })
  await expect.poll(() => textOf(admin.getByTestId('block-objective').locator('.ProseMirror'))).toBe(SOUND)
  await author.getByTestId('suggest-rewrite').click()
  await expect(author.getByTestId('suggestion-error')).toHaveText('هذا الهدف سليم وفق قواعد حراك، فلا يحتاج إلى إعادة صياغة.')
})

test('a rejected rewrite changes nothing; an accepted one replaces the objective for everyone', async ({ browser }) => {
  test.setTimeout(90_000)
  const admin = await signIn(browser, 'multi@example.com')
  const author = await signIn(browser, 'author@example.com')
  const { versionId } = await freshProgram(admin)
  await openLive(admin, versionId)
  await openLive(author, versionId)
  await draftWithObjective(admin, author, WEAK)

  const decisions = await mockSuggestion(author, {
    kind: 'rewrite',
    original: WEAK,
    result: { objective: SOUND, confidence: 'medium', explanation: 'استبدلت «يفهم» بفعل ملاحظ.' },
  })
  await author.getByTestId('suggest-rewrite').click()
  await expect(author.getByTestId('suggestion-text')).toHaveText(SOUND)
  await expect(author.getByTestId('rewrite-suggestion')).toContainText('اقتراح من الذكاء الاصطناعي')
  await expect(author.getByTestId('rewrite-suggestion')).toContainText('ثقة متوسطة')
  await author.screenshot({ path: 'e2e/screenshots/60-rewrite-suggestion-ar.png', fullPage: true })

  // Rejecting can be taken back before it is sent; once sent, it carries its reason and leaves the text as it is.
  await author.getByTestId('suggestion-dismiss').click()
  await author.getByTestId('suggestion-dismiss-cancel').click()
  await expect(author.getByTestId('suggestion-accept')).toBeVisible()
  await author.getByTestId('suggestion-dismiss').click()
  await author.getByTestId('suggestion-dismiss-reason').fill('غيّر المعنى')
  await author.getByTestId('suggestion-dismiss-confirm').click()
  await expect(author.getByTestId('suggestion-outcome')).toHaveAttribute('data-status', 'dismissed')
  expect(decisions).toEqual([{ decision: 'dismissed', body: { reason: 'غيّر المعنى' } }])
  expect(await textOf(author.getByTestId('block-objective').locator('.ProseMirror'))).toBe(WEAK)
  expect(await textOf(admin.getByTestId('block-objective').locator('.ProseMirror'))).toBe(WEAK)

  await author.getByTestId('suggestion-outcome').getByRole('button').click()
  await author.getByTestId('suggest-rewrite').click()
  await author.getByTestId('suggestion-accept').click()
  await expect(author.getByTestId('suggestion-outcome')).toHaveAttribute('data-status', 'accepted')
  await expect(author.getByTestId('suggestion-outcome')).toContainText('استُبدلت به صياغة الهدف')
  await expect.poll(() => textOf(admin.getByTestId('block-objective').locator('.ProseMirror'))).toBe(SOUND)
  // The live document is the content: the rows follow it.
  await api(admin, 'GET', `/api/program-versions/${versionId}/diff/${versionId}/`)
  const tree = await api<{ blocks: Array<{ content: unknown }> }>(admin, 'GET', `/api/program-versions/${versionId}/tree/`)
  expect(JSON.stringify(tree.blocks[0].content)).toContain(SOUND)
  expect(decisions[1]).toEqual({ decision: 'accepted', body: null })
})

test('an accepted outline adds its nodes, objectives and competency links for everyone', async ({ browser }) => {
  test.setTimeout(90_000)
  const admin = await signIn(browser, 'multi@example.com')
  const author = await signIn(browser, 'author@example.com')
  const { versionId } = await freshProgram(admin)
  const version = await api<{ framework: { id: number } }>(admin, 'GET', `/api/program-versions/${versionId}/`)
  const framework = await api<{ competencies: Array<{ competency_key: string; code: string }> }>(admin, 'GET', `/api/framework-versions/${version.framework.id}/`)
  const competency = framework.competencies[0]
  await openLive(admin, versionId)
  await openLive(author, versionId)

  const decisions = await mockSuggestion(author, {
    kind: 'outline',
    original: null,
    result: {
      nodes: [
        { ref: 'n1', parent: '', title: 'السلامة في الموقع' },
        { ref: 'n2', parent: 'n1', title: 'الإسعافات الأولية' },
      ],
      objectives: [{ node: 'n2', competency: competency.code, competency_key: competency.competency_key, text: SOUND }],
      dropped: { nodes: 0, objectives: 1 },
      confidence: 'low',
      explanation: 'وحدة بدرس واحد.',
    },
  })
  await author.getByTestId('suggest-outline').click()
  await expect(author.getByTestId('outline-node')).toHaveCount(2)
  await expect(author.getByTestId('outline-objective')).toContainText(competency.code)
  await expect(author.getByTestId('outline-suggestion')).toContainText('أهداف 1')
  await author.screenshot({ path: 'e2e/screenshots/61-outline-suggestion-ar.png', fullPage: true })

  // The answer being read survives a reload of the page.
  await author.reload()
  await expect(author.getByTestId('tree')).toBeVisible()
  await expect(author.getByTestId('outline-node')).toHaveCount(2)

  // Accepting is recorded before anything is written: when the server refuses it (another editor accepted it
  // first), the document is left as it is.
  await author.route(
    /\/api\/suggestions\/901\/accept\/$/,
    (route) => route.fulfill({ status: 409, json: { error: { code: 'suggestion_not_open', message: '' } } }),
    { times: 1 },
  )
  await author.getByTestId('suggestion-accept').click()
  await expect(author.getByTestId('suggestion-error')).toBeVisible()
  await expect(author.getByTestId('tree')).toContainText('الشجرة فارغة')
  expect(await author.getByTestId('node-السلامة في الموقع').count()).toBe(0)
  await author.getByTestId('suggestion-accept').click()
  await expect(author.getByTestId('suggestion-outcome')).toHaveAttribute('data-status', 'accepted')
  await expect(admin.getByTestId('node-السلامة في الموقع')).toBeVisible()
  await expect(admin.getByTestId('node-الإسعافات الأولية')).toBeVisible()
  await expect.poll(() => textOf(admin.getByTestId('block-objective').locator('.ProseMirror'))).toBe(SOUND)
  await expect(admin.getByTestId('block-objective').getByTestId('alignment')).toContainText(competency.code)
  expect(decisions).toEqual([{ decision: 'accepted', body: null }])
})

// Task 4.9: an import is laid out by Harak 1's rules (here without any model), previewed, and reaches the
// document only when the author accepts it.
const CURRICULUM = `برنامج السلامة المهنية للفنيين

الوحدة الأولى: مخاطر بيئة العمل

الدرس الأول: تحديد المخاطر
الأهداف:
أن يعدد المتدرب أنواع المخاطر في موقع العمل.
أن يصف المتدرب مصدر كل خطر بدقة.
الأنشطة:
نشاط 1: جولة ميدانية في الورشة لرصد المخاطر.
التقويم:
اختبار قصير من عشرة أسئلة.
`

test('an import is laid out by the rules, previewed, and added only when accepted', async ({ browser }) => {
  test.setTimeout(90_000)
  const admin = await signIn(browser, 'multi@example.com')
  const author = await signIn(browser, 'author@example.com')
  const { versionId } = await freshProgram(admin)
  await openLive(admin, versionId)
  await openLive(author, versionId)

  // Rejected: nothing reaches the document.
  await author.getByTestId('import-open').click()
  await author.getByTestId('import-text').fill(CURRICULUM)
  await author.getByTestId('import-submit').click()
  await expect(author.getByTestId('import-suggestion')).toHaveAttribute('data-source', 'rules')
  await author.getByTestId('suggestion-dismiss').click()
  await author.getByTestId('suggestion-dismiss-confirm').click()
  await expect(author.getByTestId('suggestion-outcome')).toHaveAttribute('data-status', 'dismissed')
  const empty = await api<{ nodes: unknown[] }>(admin, 'GET', `/api/program-versions/${versionId}/tree/`)
  expect(empty.nodes).toEqual([])
  expect(await author.getByTestId('tree').getByTestId(/^node-/).count()).toBe(0)

  // Accepted: the layout becomes the document for everyone.
  await author.getByTestId('suggestion-outcome').getByRole('button').click()
  await author.getByTestId('import-open').click()
  await author.getByTestId('import-text').fill(CURRICULUM)
  await author.getByTestId('import-submit').click()
  const preview = author.getByTestId('import-suggestion')
  await expect(preview.getByTestId('import-rules-note')).toContainText('الذكاء الاصطناعي غير مُعدّ')
  await expect(preview.getByTestId('import-node')).toHaveCount(2)
  await expect(preview.locator('[data-testid="import-block"][data-type="objective"]')).toHaveCount(2)
  await expect(preview.getByTestId('import-unplaced')).toContainText('1')
  await author.screenshot({ path: 'e2e/screenshots/62-import-preview-ar.png', fullPage: true })
  await author.getByTestId('suggestion-accept').click()
  await expect(author.getByTestId('suggestion-outcome')).toHaveAttribute('data-status', 'accepted')
  await expect(admin.getByTestId('node-الوحدة الأولى: مخاطر بيئة العمل')).toBeVisible()
  await expect(admin.getByTestId('node-الدرس الأول: تحديد المخاطر')).toBeVisible()
  await expect(admin.getByTestId('block-objective')).toHaveCount(2)
  await expect(admin.getByTestId('block-activity')).toHaveCount(1)

  const listed = await api<Array<{ kind: string; status: string }>>(admin, 'GET', `/api/program-versions/${versionId}/suggestions/`)
  expect(listed.map((s) => [s.kind, s.status])).toEqual([
    ['import', 'accepted'],
    ['import', 'dismissed'],
  ])
})

// Tasks 7.1 and 7.2: the curriculum as a Word file. Its text comes back into the box for the author to check, and
// the same preview follows; a scanned PDF says why it cannot be read, and the text is pasted instead.
test('an import from a Word file shows its text, then the same preview; a scanned PDF is pasted instead', async ({ browser }) => {
  test.setTimeout(120_000)
  const admin = await signIn(browser, 'multi@example.com')
  const author = await signIn(browser, 'author@example.com')
  const { versionId } = await freshProgram(admin)
  await openLive(author, versionId)

  await author.getByTestId('import-open').click()
  await author.getByTestId('import-file').setInputFiles('e2e/fixtures/scanned.pdf')
  await expect(author.getByTestId('import-file-error')).toContainText('الصق النص')
  // The refusal leaves the paste box, and pasting goes on to the same preview (phase 7 review).
  await author.getByTestId('import-text').fill(CURRICULUM)
  await author.getByTestId('import-submit').click()
  await expect(author.getByTestId('import-suggestion').getByTestId('import-node')).toHaveCount(2)
  await author.getByTestId('suggestion-dismiss').click()
  await author.getByTestId('suggestion-dismiss-confirm').click()
  await expect(author.getByTestId('suggestion-outcome')).toHaveAttribute('data-status', 'dismissed')
  await author.getByTestId('suggestion-outcome').getByRole('button').click()

  await author.getByTestId('import-open').click()
  await author.getByTestId('import-file').setInputFiles('e2e/fixtures/curriculum.docx')
  await expect(author.getByTestId('import-file-read')).toContainText('curriculum.docx')
  await expect(author.getByTestId('import-text')).toHaveValue(/أن يعدد المتدرب أنواع المخاطر في موقع العمل/)
  await author.getByTestId('import-submit').click()
  const preview = author.getByTestId('import-suggestion')
  await expect(preview.getByTestId('import-node')).toHaveCount(2)
  await expect(preview.locator('[data-testid="import-block"][data-type="objective"]')).toHaveCount(2)
  await author.screenshot({ path: 'e2e/screenshots/63-import-from-word-ar.png', fullPage: true })
  await author.getByTestId('suggestion-accept').click()
  await expect(author.getByTestId('suggestion-outcome')).toHaveAttribute('data-status', 'accepted')
  await expect(author.getByTestId('node-الدرس الأول: تحديد المخاطر')).toBeVisible()
})
