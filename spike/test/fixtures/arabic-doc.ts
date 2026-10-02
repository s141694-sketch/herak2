/**
 * Fixed fixture for round-trip tests: Arabic with diacritics, English, mixed
 * runs, Arabic-Indic and Western digits, Arabic punctuation, invisible bidi
 * controls, marks, lists, headings, quotes and hard breaks.
 */
export const ARABIC_FIXTURE_JSON = {
  type: 'doc',
  content: [
    { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'الوحدة الأولى: مقدّمة في السلامة المهنيّة' }] },
    {
      type: 'paragraph',
      content: [
        { type: 'text', text: 'يَصِفُ المُتَدَرِّبُ خُطُواتِ الإجراءِ ' },
        { type: 'text', marks: [{ type: 'bold' }], text: 'بدقّة' },
        { type: 'text', text: '، ثم يُطبّقها؛ هل فهمت؟' },
      ],
    },
    {
      type: 'paragraph',
      content: [
        { type: 'text', text: 'Mixed run: المعيار ' },
        { type: 'text', marks: [{ type: 'code' }], text: 'ISO 45001' },
        { type: 'text', text: ' يُطبَّق في ' },
        { type: 'text', marks: [{ type: 'italic' }], text: 'all sites' },
        { type: 'text', text: ' بنسبة ١٠٠٪ (100%).' },
      ],
    },
    { type: 'paragraph', content: [{ type: 'text', text: 'الأرقام: ٠١٢٣٤٥٦٧٨٩ و 0123456789 والتاريخ ٢٠٢٦/١٠/٠٣' }] },
    { type: 'paragraph', content: [{ type: 'text', text: 'علامات خفيّة: ‏نص‎ ثم ‫كلمة‬ ثم ب‌لا وــمدّ.' }] },
    {
      type: 'bulletList',
      content: [
        { type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'الهدف الأول' }] }] },
        {
          type: 'listItem',
          content: [
            { type: 'paragraph', content: [{ type: 'text', text: 'الهدف الثاني' }] },
            {
              type: 'bulletList',
              content: [{ type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'فرعي: sub-item' }] }] }],
            },
          ],
        },
      ],
    },
    {
      type: 'orderedList',
      attrs: { start: 3 },
      content: [
        { type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'الخطوة الثالثة' }] }] },
        { type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Step four' }] }] },
      ],
    },
    { type: 'blockquote', content: [{ type: 'paragraph', content: [{ type: 'text', text: '«اقتباس» من المرجع “Quoted”.' }] }] },
    {
      type: 'paragraph',
      content: [{ type: 'text', text: 'سطر أول' }, { type: 'hardBreak' }, { type: 'text', text: 'سطر ثانٍ' }],
    },
    { type: 'paragraph' },
    { type: 'codeBlock', attrs: { language: null }, content: [{ type: 'text', text: 'print("مرحبا")\nreturn 1' }] },
  ],
}
