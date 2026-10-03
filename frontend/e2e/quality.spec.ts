import { expect, type Page, test } from '@playwright/test'

import { freshProgram, openLive, signIn } from './helpers'

// Task 4.10: the quality report beside the editor, counts rolled up on the tree, dismissal with a reason, and the
// rule and AI readings side by side where they disagree; in Arabic and in English.

const WEAK = 'أن يفهم المتدرب أهمية الإسعافات'

async function draftWithWeakObjective(page: Page) {
  await page.getByRole('textbox', { name: 'إضافة وحدة' }).fill('الوحدة')
  await page.getByRole('textbox', { name: 'إضافة وحدة' }).press('Enter')
  await page.getByTestId('add-block-الوحدة').getByRole('button').click()
  await page.getByTestId('block-objective').locator('.ProseMirror').click()
  await page.keyboard.type(WEAK)
}

const finding = (page: Page, kind: string) => page.locator(`[data-testid="quality-finding"][data-kind="${kind}"]`)

test('findings appear beside the editor and on the tree, and can be dismissed with a reason and restored', async ({ browser }) => {
  test.setTimeout(120_000)
  const admin = await signIn(browser, 'multi@example.com')
  const { versionId } = await freshProgram(admin)
  await openLive(admin, versionId)
  await expect(admin.getByTestId('quality-panel')).toContainText('لم يُفحص')
  await draftWithWeakObjective(admin)

  // Each save runs the light check; the panel follows it.
  await expect(finding(admin, 'objective_unmeasurable')).toContainText('«يفهم»', { timeout: 20_000 })
  await expect(finding(admin, 'objective_unmeasurable')).toContainText('قاعدة')
  await expect(finding(admin, 'node_missing_assessment')).toContainText('الوحدة')
  const warnings = Number(await admin.getByTestId('quality-count-warning').textContent())
  expect(warnings).toBeGreaterThanOrEqual(3)
  await expect(admin.getByTestId('node-الوحدة').getByTestId('node-rollup').first()).toContainText(String(warnings))
  await admin.screenshot({ path: 'e2e/screenshots/70-quality-panel-ar.png', fullPage: true })

  // Dismissed with a reason: it leaves the open list and the counts, and stays one click away.
  await finding(admin, 'objective_unmeasurable').getByTestId('finding-dismiss').click()
  await finding(admin, 'objective_unmeasurable').getByTestId('finding-dismiss-reason').fill('مقبول في هذا البرنامج')
  await finding(admin, 'objective_unmeasurable').getByTestId('finding-dismiss-confirm').click()
  await expect(finding(admin, 'objective_unmeasurable')).toHaveCount(0)
  await expect(admin.getByTestId('quality-count-warning')).toHaveText(String(warnings - 1))
  await admin.getByTestId('quality-show-dismissed').click()
  await expect(finding(admin, 'objective_unmeasurable')).toContainText('مقبول في هذا البرنامج')
  await finding(admin, 'objective_unmeasurable').getByTestId('finding-restore').click()
  await expect(admin.getByTestId('quality-count-warning')).toHaveText(String(warnings))

  // The full check on request.
  await admin.getByTestId('quality-run').click()
  await expect(admin.getByTestId('quality-status')).toContainText('فحص كامل', { timeout: 20_000 })
})

test('the report reads in English, with the language of the interface', async ({ browser }) => {
  test.setTimeout(90_000)
  const admin = await signIn(browser, 'multi@example.com')
  const { versionId } = await freshProgram(admin)
  await openLive(admin, versionId)
  await draftWithWeakObjective(admin)
  await expect(finding(admin, 'objective_unmeasurable')).toBeVisible({ timeout: 20_000 })
  await admin.getByRole('button', { name: 'اللغة' }).click()
  await expect(admin.locator('html')).toHaveAttribute('dir', 'ltr')
  await expect(finding(admin, 'objective_unmeasurable')).toContainText('The verb «يفهم» is not measurable')
  await expect(finding(admin, 'objective_unmeasurable')).toContainText('Rule')
  await expect(admin.getByTestId('quality-panel')).toContainText('Quality report')
  await admin.screenshot({ path: 'e2e/screenshots/71-quality-panel-en.png', fullPage: true })
})

test('where the rule and the AI read an objective differently, both readings are shown', async ({ browser }) => {
  test.setTimeout(90_000)
  const admin = await signIn(browser, 'multi@example.com')
  const { versionId } = await freshProgram(admin)
  await admin.route(/\/api\/program-versions\/\d+\/quality\/$/, (route) =>
    route.fulfill({
      json: {
        id: 1,
        version: versionId,
        status: 'complete',
        last_run: 'full',
        rules_version: 'r',
        ai_prompts: {},
        ai_models: {},
        counts: { critical: 0, warning: 0, info: 1 },
        started_at: null,
        finished_at: '2026-10-03T12:00:00Z',
        error: '',
        objectives: [],
        rollup: {},
        findings: [
          {
            id: 7,
            kind: 'bloom_disagreement',
            severity: 'info',
            source: 'ai',
            confidence: 'low',
            node_key: null,
            block_key: null,
            competency: null,
            params: {
              rule: { domain: 'cognitive', level_id: 2, level: 'فهم' },
              ai: { domain: 'cognitive', level_id: 3, level: 'تطبيق', verb: 'يطبق' },
            },
            explanation: 'الفعل يدل على أداء عملي.',
            dismissal: null,
          },
        ],
      },
    }),
  )
  await openLive(admin, versionId)
  const disagreement = finding(admin, 'bloom_disagreement')
  await expect(disagreement).toContainText('القاعدة: فهم (المجال المعرفي)')
  await expect(disagreement).toContainText('الذكاء الاصطناعي: تطبيق (المجال المعرفي)')
  await expect(disagreement).toContainText('ثقة منخفضة')
  await expect(disagreement).toContainText('الفعل يدل على أداء عملي.')
})
