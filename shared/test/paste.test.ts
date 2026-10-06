/**
 * Word's lists, pasted (decision D5; phase 0 report, recommendation 4): Word marks each list item as a paragraph
 * styled "mso-list:lN levelM", its bullet or number written as text the editor would keep. They become real lists.
 */
import { describe, expect, it } from 'vitest'

import { wordLists } from '../src/paste'

const item = (level: number, marker: string, text: string, list = 'l0') =>
  `<p class=MsoListParagraphCxSpMiddle dir=RTL style='margin-right:36.0pt;text-indent:-18.0pt;mso-list:${list} level${level} lfo1'>` +
  `<![if !supportLists]><span style='font-family:Symbol'>${marker}<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp;&nbsp; </span></span><![endif]>` +
  `<span lang=AR-SA>${text}</span></p>`

describe('Word lists pasted into a block', () => {
  it('become a bullet list without Word’s bullets', () => {
    const html = `<p class=MsoNormal>الأهداف:</p>\n${item(1, '·', 'يصف المتدرب الخطوات')}\n${item(1, '·', 'يطبق المعيار')}\n<p class=MsoNormal>التقويم</p>`
    const out = wordLists(html)
    expect(out).toContain('<p class=MsoNormal>الأهداف:</p>')
    expect(out).toContain('<ul><li><p><span lang=AR-SA>يصف المتدرب الخطوات</span></p></li><li><p><span lang=AR-SA>يطبق المعيار</span></p></li></ul>')
    expect(out).not.toContain('·')
    expect(out).not.toMatch(/mso-list|supportLists/)
    expect(out).toContain('<p class=MsoNormal>التقويم</p>')
  })

  it('become numbered lists, keeping where the numbering starts', () => {
    const out = wordLists(`${item(1, '3.', 'الخطوة الثالثة')}${item(1, '4.', 'الخطوة الرابعة')}`)
    expect(out).toBe('<ol start="3"><li><p><span lang=AR-SA>الخطوة الثالثة</span></p></li><li><p><span lang=AR-SA>الخطوة الرابعة</span></p></li></ol>')
    expect(wordLists(item(1, '١.', 'أولًا'))).toMatch(/^<ol><li>/)
    expect(wordLists(item(1, 'أ)', 'أولًا'))).toMatch(/^<ol><li>/)
  })

  it('nest by their level', () => {
    const out = wordLists(`${item(1, '·', 'الخوذة')}${item(2, 'o', 'البطانة')}${item(2, 'o', 'الحزام')}${item(1, '·', 'النظارة')}`)
    expect(out).toBe(
      '<ul><li><p><span lang=AR-SA>الخوذة</span></p><ul><li><p><span lang=AR-SA>البطانة</span></p></li>' +
        '<li><p><span lang=AR-SA>الحزام</span></p></li></ul></li><li><p><span lang=AR-SA>النظارة</span></p></li></ul>',
    )
  })

  it('also read the marker Word writes as an mso-list:Ignore span, as browsers hand it over', () => {
    const html =
      `<p style="mso-list:l1 level1 lfo2"><!--[if !supportLists]--><span style="mso-list:Ignore">1.<span style="font:7pt">&nbsp; </span></span><!--[endif]-->أول</p>` +
      `<p style="mso-list:l1 level1 lfo2"><span style="mso-list:Ignore">2.<span>&nbsp;</span></span>ثانٍ</p>`
    expect(wordLists(html)).toBe('<ol><li><p>أول</p></li><li><p>ثانٍ</p></li></ol>')
  })

  it('leave anything that is not from Word as it is', () => {
    const html = '<ul><li><p>قائمة حقيقية</p></li></ul><p>نص</p>'
    expect(wordLists(html)).toBe(html)
  })

  it('keep two lists apart when something stands between them', () => {
    const out = wordLists(`${item(1, '·', 'أ')}<p class=MsoNormal>فاصل</p>${item(1, '·', 'ب')}`)
    expect(out).toBe('<ul><li><p><span lang=AR-SA>أ</span></p></li></ul><p class=MsoNormal>فاصل</p><ul><li><p><span lang=AR-SA>ب</span></p></li></ul>')
  })
})
