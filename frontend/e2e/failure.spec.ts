import { expect, test } from '@playwright/test'

import { api, freshProgram, inEditor, openLive, signIn } from './helpers'

// Task 3.8: when the live document cannot be turned into valid rows, the last good rows stay,
// editors see the problem at once, and submission is blocked with a clear message until it is fixed.

interface Tree {
  blocks: Array<{ content: unknown }>
}

test('a document the server rejects keeps the last good rows and blocks submission until fixed', async ({ browser }) => {
  test.setTimeout(120_000)
  const admin = await signIn(browser, 'multi@example.com')
  const { versionId } = await freshProgram(admin)
  await openLive(admin, versionId)

  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).fill('الوحدة')
  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).press('Enter')
  await admin.getByTestId('add-block-الوحدة').getByRole('button').click()
  await admin.getByTestId('block-objective').locator('.ProseMirror').click()
  await admin.keyboard.type('نص سليم')
  // Comparing a version with itself first takes a snapshot of its live document, so the rows are current.
  await api(admin, 'GET', `/api/program-versions/${versionId}/diff/${versionId}/`)
  const good = await api<Tree>(admin, 'GET', `/api/program-versions/${versionId}/tree/`)
  expect(JSON.stringify(good.blocks[0].content)).toContain('نص سليم')

  // A client slips in a javascript: link, which the editor holds but the server's validator refuses.
  await inEditor(
    admin,
    'objective',
    "editor.chain().focus('end').insertContent({ type: 'text', text: ' رابط', marks: [{ type: 'link', attrs: { href: 'javascript:alert(1)' } }] }).run()",
  )
  await expect(admin.getByTestId('live-save-error')).toBeVisible({ timeout: 20_000 })
  await expect(admin.getByTestId('live-save-error')).toContainText('تعذّر حفظ آخر التغييرات')
  await admin.screenshot({ path: 'e2e/screenshots/50-save-failed-ar.png', fullPage: true })

  const kept = await api<Tree>(admin, 'GET', `/api/program-versions/${versionId}/tree/`)
  expect(JSON.stringify(kept.blocks[0].content)).not.toContain('javascript')
  expect(JSON.stringify(kept.blocks[0].content)).toContain('نص سليم')

  await admin.getByTestId('submit-version').click()
  await expect(admin.getByTestId('version-error')).toHaveText(
    'تعذّر حفظ آخر التغييرات، لذلك لم يُرسل البرنامج. راجع المحتوى ثم حاول مرة أخرى.',
  )
  const still = await api<{ status: string }>(admin, 'GET', `/api/program-versions/${versionId}/`)
  expect(still.status).toBe('draft')

  // Removing the link fixes the document: the notice clears and submission goes through.
  await inEditor(admin, 'objective', 'editor.chain().selectAll().unsetLink().run()')
  await expect(admin.getByTestId('live-save-error')).toHaveCount(0, { timeout: 20_000 })
  await admin.getByTestId('submit-version').click()
  await expect(admin.getByTestId('live-status')).toHaveAttribute('data-mode', 'read')
  const submitted = await api<Tree>(admin, 'GET', `/api/program-versions/${versionId}/tree/`)
  expect(JSON.stringify(submitted.blocks[0].content)).toContain('نص سليم رابط')
  expect(JSON.stringify(submitted.blocks[0].content)).not.toContain('javascript')
})
