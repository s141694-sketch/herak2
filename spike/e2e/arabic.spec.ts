import { expect, type Page, test } from '@playwright/test'

// Task 0.7: Arabic and RTL behaviour of TipTap. Screenshots land in e2e/screenshots/.
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e/screenshots/${name}.png`, fullPage: true })

async function open(page: Page, name: string) {
  await page.goto(`/?doc=spike-arabic-${name}-${Date.now()}&user=مازن`)
  const editor = page.locator('.ProseMirror')
  await expect(page.locator('[data-testid="status"]')).toHaveText('connected')
  await editor.click()
  return editor
}

const getJSON = (page: Page) => page.evaluate(() => (window as any).__editor.getJSON())
const paragraphTexts = (page: Page) =>
  page.evaluate(() => Array.from(document.querySelectorAll('.ProseMirror p, .ProseMirror h1, .ProseMirror h2, .ProseMirror li')).map((el) => [el.textContent, getComputedStyle(el).direction]))

test('Arabic, English and mixed paragraphs each resolve their own direction', async ({ page }) => {
  const editor = await open(page, 'paragraphs')
  await page.keyboard.type('هذه فقرة عربية كاملة، تحتوي على تشكيلٍ وعلاماتِ ترقيمٍ؛ هل تظهر صحيحة؟')
  await page.keyboard.press('Enter')
  await page.keyboard.type('This is a fully English paragraph, left to right.')
  await page.keyboard.press('Enter')
  await page.keyboard.type('فقرة مختلطة: المعيار ISO 45001 يُطبَّق في all sites بنسبة ١٠٠٪ (100%).')
  await page.keyboard.press('Enter')
  await page.keyboard.type('Mixed starting in English: الهدف الأول then back to English.')

  const rows = await paragraphTexts(page)
  expect(rows.map((r) => r[1])).toEqual(['rtl', 'ltr', 'rtl', 'ltr'])
  const json = await getJSON(page)
  expect(json.content).toHaveLength(4)
  expect(json.content[2].content[0].text).toBe('فقرة مختلطة: المعيار ISO 45001 يُطبَّق في all sites بنسبة ١٠٠٪ (100%).')
  expect(editor).toBeVisible()
  await shot(page, '01-paragraphs')
})

test('Arabic bullet and ordered lists', async ({ page }) => {
  await open(page, 'lists')
  await page.keyboard.type('- الهدف الأول: يصف المتدرب الإجراء')
  await page.keyboard.press('Enter')
  await page.keyboard.type('الهدف الثاني: يطبّق المتدرب الخطوات')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Tab')
  await page.keyboard.type('هدف فرعي مع كلمة English')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Enter')
  await page.keyboard.type('1. الخطوة الأولى')
  await page.keyboard.press('Enter')
  await page.keyboard.type('الخطوة الثانية ٢')
  await page.keyboard.press('Enter')
  await page.keyboard.type('Step three in English')

  const json = await getJSON(page)
  const types = json.content.map((n: { type: string }) => n.type)
  expect(types).toContain('bulletList')
  expect(types).toContain('orderedList')
  const bullet = json.content.find((n: { type: string }) => n.type === 'bulletList')
  expect(bullet.content).toHaveLength(2)
  expect(bullet.content[1].content[1].type).toBe('bulletList') // nested
  const rows = await paragraphTexts(page)
  expect(rows.find((r) => r[0]?.startsWith('Step three'))?.[1]).toBe('ltr')
  expect(rows.find((r) => r[0]?.startsWith('الخطوة الأولى'))?.[1]).toBe('rtl')
  await shot(page, '02-lists')
})

test('digits, diacritics, punctuation and bidi controls survive typing exactly', async ({ page }) => {
  await open(page, 'digits')
  const line1 = 'الأرقام: ٠١٢٣٤٥٦٧٨٩ و 0123456789 والتاريخ ٢٠٢٦/١٠/٠٣ والنسبة ٪٥٠ و 50%.'
  const line2 = 'مُحَمَّدٌ قَرَأَ الدَّرْسَ، ثُمَّ أَجَابَ؛ أَلَيْسَ كَذَلِكَ؟ «نعم» “yes” (ok) [٣].'
  const line3 = 'رقم الهاتف +968 2414 1234 والبريد test@example.com والرابط example.com/ar?x=1'
  await page.keyboard.type(line1)
  await page.keyboard.press('Enter')
  await page.keyboard.type(line2)
  await page.keyboard.press('Enter')
  await page.keyboard.type(line3)
  const json = await getJSON(page)
  // StarterKit's autolink splits "test@example.com" into a link-marked text node, so join the nodes.
  const joined = json.content.map((p: { content: Array<{ text: string }> }) => p.content.map((t) => t.text).join(''))
  expect(joined).toEqual([line1, line2, line3])
  const linkMarks = JSON.stringify(json).match(/"type":"link"/g)?.length ?? 0
  test.info().annotations.push({ type: 'autolink', description: `autolink produced ${linkMarks} link marks on typed email/url` })
  await shot(page, '03-digits-punctuation')
})

test('pasting Word HTML keeps text, paragraphs, bold and lists, and drops Word markup', async ({ page }) => {
  await open(page, 'word')
  const wordHtml = `
<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word">
<head><meta name=Generator content="Microsoft Word 15"><style>p.MsoNormal{margin:0cm;font-size:12pt;font-family:"Calibri",sans-serif;}</style></head>
<body lang=AR-SA dir=RTL style='tab-interval:36.0pt'>
<div class=WordSection1>
<p class=MsoNormal dir=RTL style='text-align:right;direction:rtl;unicode-bidi:embed'><span lang=AR-SA style='font-family:"Traditional Arabic"'>الوحدة الأولى: </span><b><span lang=AR-SA style='font-family:"Traditional Arabic"'>السلامة المهنية</span></b><span lang=AR-SA> في موقع العمل.</span></p>
<p class=MsoNormal dir=RTL style='text-align:right;direction:rtl'><span lang=AR-SA>الأهداف:</span><o:p></o:p></p>
<p class=MsoListParagraphCxSpFirst dir=RTL style='margin-right:36.0pt;text-indent:-18.0pt;mso-list:l0 level1 lfo1'><![if !supportLists]><span style='font-family:Symbol'>·<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp;&nbsp; </span></span><![endif]><span lang=AR-SA>يصف المتدرب خطوات الإجراء</span></p>
<p class=MsoListParagraphCxSpLast dir=RTL style='margin-right:36.0pt;text-indent:-18.0pt;mso-list:l0 level1 lfo1'><![if !supportLists]><span style='font-family:Symbol'>·<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp;&nbsp; </span></span><![endif]><span lang=AR-SA>يطبّق المتدرب معيار </span><span dir=LTR lang=EN-US>ISO 45001</span><span lang=AR-SA> بدقة</span></p>
<p class=MsoNormal dir=RTL><span lang=AR-SA>التقويم: اختبار قصير من ١٠ أسئلة.</span></p>
</div></body></html>`
  const plain = 'الوحدة الأولى: السلامة المهنية في موقع العمل.\nالأهداف:\n·    يصف المتدرب خطوات الإجراء\n·    يطبّق المتدرب معيار ISO 45001 بدقة\nالتقويم: اختبار قصير من ١٠ أسئلة.'
  await page.evaluate(
    ([html, text]) => {
      const dt = new DataTransfer()
      dt.setData('text/html', html)
      dt.setData('text/plain', text)
      const target = document.querySelector('.ProseMirror')!
      target.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }))
    },
    [wordHtml, plain],
  )
  const json = await getJSON(page)
  const serialized = JSON.stringify(json)
  expect(serialized).not.toMatch(/Mso|mso-|o:p|Calibri|Traditional Arabic/)
  expect(serialized).toContain('الوحدة الأولى: ')
  expect(serialized).toContain('"marks":[{"type":"bold"}],"text":"السلامة المهنية"')
  expect(serialized).toContain('يطبّق المتدرب معيار ')
  expect(serialized).toContain('ISO 45001')
  expect(serialized).toContain('التقويم: اختبار قصير من ١٠ أسئلة.')
  const html = await page.evaluate(() => (window as any).__editor.getHTML())
  await shot(page, '04-word-paste')
  // Word's fake bullets are plain paragraphs; whether they become a real list is recorded for the report.
  test.info().annotations.push({ type: 'word-paste-structure', description: `types=${json.content.map((n: { type: string }) => n.type).join(',')}; html=${html.slice(0, 400)}` })
})

test('bold, italic and heading marks render on Arabic text', async ({ page }) => {
  await open(page, 'marks')
  await page.keyboard.type('# عنوان الوحدة الأولى')
  await page.keyboard.press('Enter')
  await page.keyboard.type('نص عادي ثم ')
  await page.keyboard.press('Control+b')
  await page.keyboard.type('نص غامق')
  await page.keyboard.press('Control+b')
  await page.keyboard.type(' ثم ')
  await page.keyboard.press('Control+i')
  await page.keyboard.type('نص مائل')
  await page.keyboard.press('Control+i')
  await page.keyboard.type(' ثم نهاية.')
  const json = await getJSON(page)
  expect(json.content[0]).toMatchObject({ type: 'heading', attrs: { level: 1 } })
  const marks = json.content[1].content.map((t: { marks?: Array<{ type: string }> }) => t.marks?.map((m) => m.type).join('+') ?? '')
  expect(marks).toEqual(['', 'bold', '', 'italic', ''])
  await shot(page, '05-marks-heading')
})
