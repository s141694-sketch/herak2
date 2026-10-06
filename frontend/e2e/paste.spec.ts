import { expect, test } from '@playwright/test'

import { api, freshProgram, openLive, signIn } from './helpers'

// Decision D5 (phase 0 report, recommendation 4): Word's lists pasted into a block become real lists, nested and
// numbered as in Word, instead of paragraphs that begin with "·". The HTML is what Word puts on the clipboard.
const WORD = `
<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word">
<head><meta name=Generator content="Microsoft Word 15"></head>
<body lang=AR-SA dir=RTL><div class=WordSection1>
<p class=MsoNormal dir=RTL><span lang=AR-SA>الأهداف:</span><o:p></o:p></p>
<p class=MsoListParagraphCxSpFirst dir=RTL style='margin-right:36.0pt;text-indent:-18.0pt;mso-list:l0 level1 lfo1'><![if !supportLists]><span style='font-family:Symbol'>·<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp;&nbsp; </span></span><![endif]><span lang=AR-SA>يصف المتدرب خطوات الإجراء</span></p>
<p class=MsoListParagraphCxSpMiddle dir=RTL style='margin-right:72.0pt;text-indent:-18.0pt;mso-list:l0 level2 lfo1'><![if !supportLists]><span style='font-family:"Courier New"'>o<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp; </span></span><![endif]><span lang=AR-SA>بدقة وبالترتيب</span></p>
<p class=MsoListParagraphCxSpLast dir=RTL style='margin-right:36.0pt;text-indent:-18.0pt;mso-list:l0 level1 lfo1'><![if !supportLists]><span style='font-family:Symbol'>·<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp;&nbsp; </span></span><![endif]><span lang=AR-SA>يطبّق المتدرب معيار </span><span dir=LTR lang=EN-US>ISO 45001</span></p>
<p class=MsoNormal dir=RTL><span lang=AR-SA>الخطوات:</span></p>
<p class=MsoListParagraphCxSpFirst dir=RTL style='mso-list:l1 level1 lfo2'><![if !supportLists]><span lang=AR-SA>3.<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp; </span></span><![endif]><span lang=AR-SA>افحص المعدات</span></p>
<p class=MsoListParagraphCxSpLast dir=RTL style='mso-list:l1 level1 lfo2'><![if !supportLists]><span lang=AR-SA>4.<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp; </span></span><![endif]><span lang=AR-SA>سجّل النتائج</span></p>
</div></body></html>`

test('Word lists pasted into a block become real lists, nested and numbered as in Word', async ({ browser }) => {
  test.setTimeout(90_000)
  const admin = await signIn(browser, 'multi@example.com')
  const { versionId } = await freshProgram(admin)
  await openLive(admin, versionId)
  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).fill('الوحدة')
  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).press('Enter')
  const blocks = admin.getByTestId('add-block-الوحدة')
  await blocks.locator('select').selectOption('content')
  await blocks.getByRole('button').click()
  const editor = admin.getByTestId('block-content').locator('.ProseMirror')
  await editor.click()
  await editor.evaluate((target, html) => {
    const data = new DataTransfer()
    data.setData('text/html', html)
    data.setData('text/plain', 'الأهداف:\n·    يصف المتدرب خطوات الإجراء')
    target.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
  }, WORD)

  await expect(editor.locator(':scope > ul > li')).toHaveCount(2)
  await expect(editor.locator(':scope > ul > li').first().locator('ul > li')).toHaveText('بدقة وبالترتيب')
  await expect(editor.locator(':scope > ol')).toHaveAttribute('start', '3')
  await expect(editor.locator(':scope > ol > li')).toHaveText(['افحص المعدات', 'سجّل النتائج'])
  await expect(editor).not.toContainText('·')
  await admin.screenshot({ path: 'e2e/screenshots/64-word-lists-pasted-ar.png', fullPage: true })

  // The saved rows hold the lists too (comparing a version with itself first takes a snapshot of its live document).
  await expect
    .poll(async () => {
      await api(admin, 'GET', `/api/program-versions/${versionId}/diff/${versionId}/`)
      const tree = await api<{ blocks: Array<{ content: unknown }> }>(admin, 'GET', `/api/program-versions/${versionId}/tree/`)
      return JSON.stringify(tree.blocks[0]?.content ?? null)
    })
    .toMatch(/"bulletList".*"orderedList","attrs":\{[^}]*"start":3/)
})
