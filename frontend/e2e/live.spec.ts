import { expect, test } from '@playwright/test'

import { api, freshProgram, openLive, signIn, textOf } from './helpers'

// Phase 3: two people edit one draft live; submission locks it for both.
test('two editors see each other live, and submission locks the draft for both', async ({ browser }) => {
  test.setTimeout(90_000)
  const admin = await signIn(browser, 'multi@example.com')
  const author = await signIn(browser, 'author@example.com')
  const { versionId } = await freshProgram(admin)
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
