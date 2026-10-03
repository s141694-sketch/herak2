import { expect, type Page, test, type WebSocketRoute } from '@playwright/test'

import { freshProgram, openLive, signIn, textOf } from './helpers'

// Task 3.7: when the collaboration service goes away the editor turns read-only with a notice,
// then reconnects and merges what others wrote meanwhile, without a reload.

/** Routes the page's /collab sockets through a switch that can take the service "down". */
async function collabSwitch(page: Page) {
  const state = { down: false, open: [] as WebSocketRoute[] }
  await page.routeWebSocket(/\/collab/, (ws) => {
    if (state.down) {
      ws.close({ code: 1006, reason: 'service down' })
      return
    }
    ws.connectToServer()
    state.open.push(ws)
  })
  return {
    goDown: async () => {
      state.down = true
      for (const ws of state.open.splice(0)) await ws.close({ code: 1006, reason: 'service down' }).catch(() => undefined)
    },
    comeBack: () => {
      state.down = false
    },
  }
}

test('the editor goes read-only during an outage, then reconnects and merges', async ({ browser }) => {
  test.setTimeout(120_000)
  const admin = await signIn(browser, 'multi@example.com')
  const author = await signIn(browser, 'author@example.com')
  const { versionId } = await freshProgram(admin)
  const outage = await collabSwitch(author)

  await openLive(admin, versionId)
  await openLive(author, versionId)
  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).fill('الوحدة')
  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).press('Enter')
  await admin.getByTestId('add-block-الوحدة').getByRole('button').click()
  const adminEditor = admin.getByTestId('block-objective').locator('.ProseMirror')
  const authorEditor = author.getByTestId('block-objective').locator('.ProseMirror')
  await adminEditor.click()
  await admin.keyboard.type('قبل الانقطاع')
  await expect.poll(() => textOf(authorEditor)).toBe('قبل الانقطاع')
  await expect(authorEditor).toHaveAttribute('contenteditable', 'true')

  // The service goes away for the author: read-only with a clear notice, no editing controls.
  await outage.goDown()
  await expect(author.getByTestId('live-status')).not.toHaveAttribute('data-state', 'connected')
  await expect(author.getByTestId('live-status')).toHaveClass(/error|notice/)
  await expect(authorEditor).toHaveAttribute('contenteditable', 'false')
  await expect(author.getByRole('textbox', { name: 'إضافة وحدة' })).toHaveCount(0)
  await author.screenshot({ path: 'e2e/screenshots/40-outage-ar.png', fullPage: true })

  // Meanwhile the admin keeps writing.
  await adminEditor.click()
  await admin.keyboard.press('End')
  await admin.keyboard.type(' وأثناءه')

  // The service comes back: the author reconnects on its own, catches up, and can edit again.
  outage.comeBack()
  await expect(author.getByTestId('live-status')).toHaveAttribute('data-state', 'connected', { timeout: 30_000 })
  await expect.poll(() => textOf(authorEditor), { timeout: 15_000 }).toBe('قبل الانقطاع وأثناءه')
  await expect(authorEditor).toHaveAttribute('contenteditable', 'true')
  await authorEditor.click()
  await author.keyboard.press('End')
  await author.keyboard.type(' وبعده')
  await expect.poll(() => textOf(adminEditor)).toBe('قبل الانقطاع وأثناءه وبعده')
})
