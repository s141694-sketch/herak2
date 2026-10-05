import { expect, type Page, test } from '@playwright/test'

import { api, freshProgram, openLive, signIn } from './helpers'

// Phase 5 acceptance: submit -> return -> resubmit -> approve through the default workflow of the training center
// (a reviewer's stage, then an approver's), on the real services, with the pre-submit check, the comment rules,
// the reviewer's inbox and notifications.

async function draftContent(page: Page) {
  await page.getByRole('textbox', { name: 'إضافة وحدة' }).fill('الوحدة')
  await page.getByRole('textbox', { name: 'إضافة وحدة' }).press('Enter')
  await page.getByTestId('add-block-الوحدة').getByRole('button').click()
  await page.getByTestId('block-objective').locator('.ProseMirror').click()
  await page.keyboard.type('أن يعدد المتدرب مخاطر الموقع')
}

/** Submits the open draft; its target competency has no assessment, so the pre-submit check asks for a reason. */
async function submitWithReason(author: Page, reason: string) {
  await author.getByTestId('submit-version').click()
  await expect(author.getByTestId('version-error')).toHaveText('في المحتوى ملاحظات حرجة: اكتب سبب الإرسال رغمها.')
  await author.getByTestId('submit-reason').fill(reason)
  await author.getByTestId('submit-version').click()
  await expect(author.getByTestId('review-panel')).toBeVisible()
}

async function takeAndOpen(page: Page, title: string) {
  await page.goto('/tasks')
  const row = page.getByTestId('task-list').locator('li', { hasText: title })
  await row.getByTestId('task-claim').click()
  await expect(row.getByTestId('task-release')).toBeVisible()
  await row.getByTestId('task-open').click()
  return page.getByTestId('review-panel')
}

test('a version is submitted, returned, resubmitted and approved', async ({ browser }) => {
  test.setTimeout(180_000)
  const admin = await signIn(browser, 'multi@example.com')
  const { programId, versionId } = await freshProgram(admin)
  const { title } = await api<{ title: string }>(admin, 'GET', `/api/programs/${programId}/`)
  const detail = await api<{ framework: { id: number } }>(admin, 'GET', `/api/program-versions/${versionId}/`)
  const framework = await api<{ competencies: Array<{ id: number }> }>(admin, 'GET', `/api/framework-versions/${detail.framework.id}/`)
  await api(admin, 'PUT', `/api/program-versions/${versionId}/targets/`, [framework.competencies[0].id])

  // The author writes and submits; the critical finding needs a reason, which the reviewer will see.
  const author = await signIn(browser, 'author@example.com')
  // The e2e database outlives a run: start from no unread notifications, so the one this test makes is seen.
  await api(author, 'POST', '/api/notifications/', { read_all: true })
  await openLive(author, versionId)
  await draftContent(author)
  await submitWithReason(author, 'التقويم في البرنامج التالي')
  await expect(author.getByTestId('live-status')).toHaveAttribute('data-state', 'locked')
  await expect(author.getByTestId('stages-progress').locator('[data-state="current"]')).toContainText('المراجعة الفنية')
  // Before any decision the authors may withdraw it.
  await expect(author.getByTestId('withdraw-version')).toBeVisible()

  // The reviewer finds it in the inbox, takes it, and cannot return it without a comment on the version.
  const reviewer = await signIn(browser, 'reviewer@example.com')
  let panel = await takeAndOpen(reviewer, title)
  await expect(panel.getByTestId('pre-submit')).toContainText('التقويم في البرنامج التالي')
  await reviewer.screenshot({ path: 'e2e/screenshots/80-review-panel-ar.png', fullPage: true })
  await panel.getByTestId('decision-note').fill('أضف تقويمًا للهدف')
  await panel.getByTestId('decision-return').click()
  await expect(panel.getByTestId('decision-error')).toHaveText('اكتب ملاحظة واحدة على الأقل على هذه النسخة قبل إعادتها.')
  const tree = await api<{ nodes: Array<{ node_key: string }> }>(reviewer, 'GET', `/api/program-versions/${versionId}/tree/`)
  const mustFix = await api<{ id: number }>(reviewer, 'POST', `/api/programs/${programId}/comments/`, {
    version: versionId,
    node_key: tree.nodes[0].node_key,
    body: 'أضف تقويمًا يقيس الهدف',
    category: 'must_fix',
  })
  await panel.getByTestId('decision-return').click()
  await expect(panel.getByTestId('review-outcome')).toContainText('أُعيدت هذه النسخة للتعديل، وأُنشئت مسودة جديدة.')
  await expect(panel.getByTestId('returned-program')).toHaveAttribute('href', `/programs/${programId}`)

  // The author is told, with the note; the notification leads to the program, where the new draft is.
  await author.getByTestId('notifications-toggle').click()
  const told = author.getByTestId('notification').filter({ hasText: title }).first()
  await expect(told).toHaveAttribute('data-event', 'version_returned')
  await expect(told).toHaveClass('unread')
  await expect(told).toContainText('أضف تقويمًا للهدف')
  await expect(author.getByTestId('notifications-unread')).toHaveText('1')
  await told.getByRole('button').click()
  await expect(author.getByTestId('program-heading')).toHaveText(title)
  await expect(author.getByTestId('program-workflow-fixed')).toBeVisible()

  // The author fixes it on the new draft and resubmits; it goes back to the stage that returned it.
  const versions = await api<Array<{ id: number; status: string }>>(author, 'GET', `/api/programs/${programId}/versions/`)
  const draftId = versions.find((v) => v.status === 'draft')!.id
  await api(author, 'POST', `/api/comments/${mustFix.id}/resolve/`)
  await openLive(author, draftId)
  // While fixing it, the draft shows why it came back.
  await expect(author.getByTestId('returned-panel')).toContainText('أضف تقويمًا للهدف')
  await submitWithReason(author, 'التقويم في البرنامج التالي')
  await expect(author.getByTestId('previous-submission')).toContainText('أضف تقويمًا للهدف')

  // The reviewer sees what was fixed since the return, and approves the stage.
  panel = await takeAndOpen(reviewer, title)
  await expect(panel.getByTestId('resolved-comment')).toContainText('أضف تقويمًا يقيس الهدف')
  await panel.getByTestId('decision-approve').click()
  await expect(panel.getByTestId('stages-progress').locator('[data-state="current"]')).toContainText('الاعتماد')
  // After a decision the submission can no longer be withdrawn, and the button is gone.
  await author.reload()
  await expect(author.getByTestId('review-panel')).toBeVisible()
  await expect(author.getByTestId('withdraw-version')).toHaveCount(0)

  // The approver takes the last stage and approves: the version is approved and locked.
  const approver = await signIn(browser, 'approver@example.com')
  panel = await takeAndOpen(approver, title)
  await panel.getByTestId('decision-note').fill('معتمد')
  await panel.getByTestId('decision-approve').click()
  await expect(panel.getByTestId('review-outcome')).toHaveText('اعتُمدت هذه النسخة.')
  const approved = await api<{ status: string }>(admin, 'GET', `/api/program-versions/${draftId}/`)
  expect(approved.status).toBe('approved')
  await expect(panel.getByTestId('decisions').locator('li')).toHaveCount(2)

  // The same panel in English.
  await approver.getByRole('button', { name: 'اللغة' }).click()
  await expect(approver.locator('html')).toHaveAttribute('dir', 'ltr')
  await expect(panel).toContainText('Review and approval')
  await expect(panel.getByTestId('review-outcome')).toHaveText('This version is approved.')
  await approver.screenshot({ path: 'e2e/screenshots/81-review-approved-en.png', fullPage: true })
})

test('an admin defines a workflow; others read it', async ({ browser }) => {
  test.setTimeout(90_000)
  const admin = await signIn(browser, 'multi@example.com')
  const name = `مسار قصير ${Date.now()}`.slice(0, 40)
  await admin.getByTestId('nav-workflows').click()
  await admin.getByTestId('workflow-new').click()
  const form = admin.getByTestId('workflow-form')
  await form.getByTestId('workflow-name').fill(name)
  await form.getByTestId('stage-name').fill('اعتماد مباشر')
  await form.getByTestId('stage-who').selectOption('user')
  await form.getByTestId('stage-user').selectOption({ label: 'منى الرواحية (معتمِد)' })
  await form.getByTestId('stage-days').fill('2')
  await form.getByTestId('workflow-save').click()
  const item = admin.getByTestId('workflow-item').filter({ hasText: name })
  try {
    await expect(item).toContainText('اعتماد مباشر — منى الرواحية · المهلة بأيام العمل: 2 · تعود إلى هذه المرحلة')
    await admin.screenshot({ path: 'e2e/screenshots/82-workflows-ar.png', fullPage: true })

    const author = await signIn(browser, 'author@example.com')
    await author.goto('/workflows')
    await expect(author.getByTestId('workflow-item').filter({ hasText: name })).toBeVisible()
    await expect(author.getByTestId('workflow-new')).toHaveCount(0)

    // Deleting asks first.
    admin.once('dialog', (dialog) => void dialog.accept())
    await item.getByTestId('workflow-delete').click()
    await expect(admin.getByTestId('workflow-item').filter({ hasText: name })).toHaveCount(0)
  } finally {
    // Removed whatever happened, so the seeded default stays the only workflow other tests rely on.
    const left = await api<Array<{ id: number; name: string }>>(admin, 'GET', '/api/workflow-templates/')
    for (const template of left.filter((w) => w.name === name)) await api(admin, 'DELETE', `/api/workflow-templates/${template.id}/`)
  }
})
