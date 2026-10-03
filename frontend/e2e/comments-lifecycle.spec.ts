import { expect, test } from '@playwright/test'

import { api, card, comment, freshProgram, openLive, signIn, textOf } from './helpers'

// Phase 3 review findings on comments: replies reach everyone, resolved comments stay reachable for reopening,
// a comment on a block whose node was deleted is not lost, and a version shows no comment from a later one.
test('replies reach everyone, resolved comments can be reopened, and comments follow their node and version', async ({ browser }) => {
  test.setTimeout(150_000)
  const admin = await signIn(browser, 'multi@example.com')
  const author = await signIn(browser, 'author@example.com')
  const { programId, versionId } = await freshProgram(admin)
  await openLive(admin, versionId)
  await openLive(author, versionId)

  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).fill('الوحدة')
  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).press('Enter')
  await admin.getByTestId('add-block-الوحدة').getByRole('button').click()
  await admin.getByTestId('block-objective').locator('.ProseMirror').click()
  await admin.keyboard.type('يصف المتدرب الإجراء')
  await expect.poll(() => textOf(author.getByTestId('block-objective').locator('.ProseMirror'))).toBe('يصف المتدرب الإجراء')
  await comment(admin, 'الإجراء', 'وضّح الإجراء', 'suggestion')
  await expect(card(author, 'وضّح الإجراء')).toBeVisible()

  // A reply shows at once for its writer and reaches the others without a reload.
  await card(author, 'وضّح الإجراء').getByRole('textbox', { name: 'رد' }).fill('سأوضحه')
  await card(author, 'وضّح الإجراء').getByRole('button', { name: 'رد' }).click()
  await expect(card(author, 'وضّح الإجراء')).toContainText('سأوضحه')
  await expect(card(author, 'وضّح الإجراء').getByRole('textbox', { name: 'رد' })).toHaveValue('')
  await expect(card(admin, 'وضّح الإجراء')).toContainText('سأوضحه')

  // Resolved comments leave the page but stay one click away, so a reviewer can reopen them.
  await card(author, 'وضّح الإجراء').getByTestId('comment-resolve').click()
  await expect(card(author, 'وضّح الإجراء')).toHaveCount(0)
  await expect(card(admin, 'وضّح الإجراء')).toHaveCount(0)
  await expect(admin.getByTestId('toggle-resolved')).toContainText('1')
  await admin.getByTestId('toggle-resolved').click()
  await expect(card(admin, 'وضّح الإجراء')).toHaveAttribute('data-status', 'resolved')
  await card(admin, 'وضّح الإجراء').getByTestId('comment-reopen').click()
  await expect(card(author, 'وضّح الإجراء')).toHaveAttribute('data-status', 'open')

  // Deleting the node hides its blocks; their comments wait among the comments without a place.
  const header = admin.getByTestId('node-الوحدة').locator('.node-header')
  await header.getByRole('button', { name: 'حذف' }).click()
  for (const page of [admin, author]) await expect(page.getByTestId('unanchored-comments')).toContainText('وضّح الإجراء')
  await header.getByRole('button', { name: 'استرجاع' }).click()
  for (const page of [admin, author]) {
    await expect(page.getByTestId('unanchored-comments')).toHaveCount(0)
    await expect(page.getByTestId('block-objective').getByTestId('block-comments')).toContainText('وضّح الإجراء')
  }

  // A comment made on the next version does not appear on this one.
  await admin.getByTestId('submit-version').click()
  await expect(admin.getByTestId('withdraw-version')).toBeVisible()
  await admin.getByTestId('withdraw-version').click()
  await expect(admin.getByTestId('program-versions').locator('tr')).toHaveCount(2)
  const versions = await api<Array<{ id: number; number: number }>>(admin, 'GET', `/api/programs/${programId}/versions/`)
  const next = versions.find((v) => v.number === 2)!
  await openLive(author, next.id)
  await comment(author, 'يصف', 'ملاحظة على النسخة الثانية', 'suggestion')
  await expect(card(author, 'ملاحظة على النسخة الثانية')).toBeVisible()
  await openLive(admin, versionId, 'read')
  await expect(card(admin, 'وضّح الإجراء')).toBeVisible()
  await expect(card(admin, 'ملاحظة على النسخة الثانية')).toHaveCount(0)
})
