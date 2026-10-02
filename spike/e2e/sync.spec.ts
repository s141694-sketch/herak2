import { expect, test } from '@playwright/test'

// Task 0.1 acceptance: two editors in two windows stay in sync through Hocuspocus.
test('two editors on the same document converge in both directions', async ({ browser }) => {
  const doc = `spike-sync-${Date.now()}`
  const a = await (await browser.newContext()).newPage()
  const b = await (await browser.newContext()).newPage()
  await a.goto(`/?doc=${doc}&user=علي`)
  await b.goto(`/?doc=${doc}&user=Sara`)

  const editorA = a.locator('.ProseMirror')
  const editorB = b.locator('.ProseMirror')
  await expect(editorA).toBeVisible()
  await expect(editorB).toBeVisible()
  await expect(a.locator('[data-testid="status"]')).toHaveText('connected')
  await expect(b.locator('[data-testid="status"]')).toHaveText('connected')

  await editorA.click()
  await a.keyboard.type('مرحبًا بالعالم')
  await expect(editorB).toContainText('مرحبًا بالعالم')

  await editorB.click()
  await b.keyboard.press('End')
  await b.keyboard.type(' and hello world')
  await expect(editorA).toContainText('مرحبًا بالعالم and hello world')

  // Both sides must end up with the identical ProseMirror JSON.
  const jsonA = await a.evaluate(() => (window as any).__editor.getJSON())
  const jsonB = await b.evaluate(() => (window as any).__editor.getJSON())
  expect(jsonA).toEqual(jsonB)
})
