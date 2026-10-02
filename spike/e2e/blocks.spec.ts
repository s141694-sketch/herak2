import { expect, test } from '@playwright/test'

// Task 0.2: an editor per block, each bound to the XmlFragment nested in the block's Y.Map.
test('block editors bound to nested fragments sync independently', async ({ browser }) => {
  const doc = `spike-blocks-${Date.now()}`
  const a = await (await browser.newContext()).newPage()
  await a.goto(`/?doc=${doc}&user=علي&mode=blocks`)
  await expect(a.getByTestId('block-objective-1')).toBeVisible()
  const b = await (await browser.newContext()).newPage()
  await b.goto(`/?doc=${doc}&user=Sara&mode=blocks`)
  await expect(b.getByTestId('block-content-1')).toBeVisible()

  await a.getByTestId('block-objective-1').locator('.ProseMirror').click()
  await a.keyboard.type('يصف المتدرب خطوات الإجراء')
  await expect(b.getByTestId('block-objective-1')).toContainText('يصف المتدرب خطوات الإجراء')

  await b.getByTestId('block-content-1').locator('.ProseMirror').click()
  await b.keyboard.type('Content in English')
  await expect(a.getByTestId('block-content-1')).toContainText('Content in English')

  // No leakage between blocks.
  await expect(a.getByTestId('block-content-1')).not.toContainText('يصف')
  await expect(b.getByTestId('block-objective-1')).not.toContainText('Content')
})
