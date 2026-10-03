import { expect, test } from '@playwright/test'

import { api, card, comment, freshProgram, inEditor, openLive, RANGE_OF, signIn, textOf } from './helpers'

// Task 3.6: comments anchored with Yjs relative positions survive concurrent edits, report changed text,
// move to "comments without a place" when their text is deleted, and carry into the next version.

test('comments stay on their text through concurrent edits and versions', async ({ browser }) => {
  test.setTimeout(120_000)
  const admin = await signIn(browser, 'multi@example.com')
  const author = await signIn(browser, 'author@example.com')
  const { programId, versionId } = await freshProgram(admin)
  await openLive(admin, versionId)
  await openLive(author, versionId)

  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).fill('الوحدة')
  await admin.getByRole('textbox', { name: 'إضافة وحدة' }).press('Enter')
  await admin.getByTestId('add-block-الوحدة').getByRole('button').click()
  await admin.getByTestId('block-objective').locator('.ProseMirror').click()
  await admin.keyboard.type('يصف المتدرب خطوات الإجراء بدقة')
  await expect.poll(() => textOf(author.getByTestId('block-objective').locator('.ProseMirror'))).toBe('يصف المتدرب خطوات الإجراء بدقة')

  // The reviewer-side user comments on two quotes.
  await comment(admin, 'خطوات الإجراء', 'استخدم فعلًا قابلًا للقياس', 'must_fix')
  await comment(admin, 'بدقة', 'حدد معيار الدقة', 'suggestion')
  for (const page of [admin, author]) {
    await expect(card(page, 'استخدم فعلًا')).toHaveAttribute('data-placement', 'intact')
    await expect(card(page, 'حدد معيار')).toHaveAttribute('data-placement', 'intact')
  }

  // The author edits before, at the start boundary of, and after the quote: the comments stay on their text.
  await inEditor(author, 'objective', "editor.commands.insertContentAt(1, 'أولًا، ')")
  const quote = await inEditor(author, 'objective', RANGE_OF, { quote: 'خطوات الإجراء' })
  await inEditor(author, 'objective', 'editor.commands.insertContentAt(args.from, "كل ")', quote)
  await inEditor(author, 'objective', "editor.commands.insertContentAt(editor.state.doc.content.size - 1, ' في الموقع')")
  await expect.poll(() => textOf(admin.getByTestId('block-objective').locator('.ProseMirror'))).toBe('أولًا، يصف المتدرب كل خطوات الإجراء بدقة في الموقع')
  for (const page of [admin, author]) {
    await expect(card(page, 'استخدم فعلًا')).toHaveAttribute('data-placement', 'intact')
    await expect(card(page, 'حدد معيار')).toHaveAttribute('data-placement', 'intact')
  }
  await admin.screenshot({ path: 'e2e/screenshots/30-comments-intact-ar.png', fullPage: true })

  // Text inside the quote changes: the comment says so and shows the current text.
  const word = await inEditor(author, 'objective', RANGE_OF, { quote: 'خطوات' })
  await inEditor(author, 'objective', "editor.chain().deleteRange(args).insertContentAt(args.from, 'مراحل').run()", word)
  await expect(card(admin, 'استخدم فعلًا')).toHaveAttribute('data-placement', 'changed')
  await expect(card(admin, 'استخدم فعلًا')).toContainText('مراحل الإجراء')

  // The quoted text is deleted: the comment moves to "comments without a place" for everyone.
  const gone = await inEditor(author, 'objective', RANGE_OF, { quote: 'مراحل الإجراء' })
  await inEditor(author, 'objective', 'editor.commands.deleteRange(args)', gone)
  for (const page of [admin, author]) {
    await expect(page.getByTestId('unanchored-comments')).toContainText('استخدم فعلًا قابلًا للقياس')
    await expect(page.getByTestId('block-objective').getByTestId('block-comments')).not.toContainText('استخدم فعلًا')
  }
  await admin.screenshot({ path: 'e2e/screenshots/31-comments-unanchored-ar.png', fullPage: true })

  // The open comments carry into the next version, still on their text there (the draft copies the Yjs state).
  await admin.getByTestId('submit-version').click()
  await expect(admin.getByTestId('withdraw-version')).toBeVisible()
  await admin.getByTestId('withdraw-version').click()
  await expect(admin.getByTestId('program-versions').locator('tr')).toHaveCount(2)
  const versions = await api<Array<{ id: number; number: number }>>(admin, 'GET', `/api/programs/${programId}/versions/`)
  const next = versions.find((v) => v.number === 2)!
  await openLive(author, next.id)
  await expect(card(author, 'حدد معيار')).toHaveAttribute('data-placement', 'intact')
  await expect(card(author, 'حدد معيار')).toContainText('من النسخة 1')
  await expect(author.getByTestId('unanchored-comments')).toContainText('استخدم فعلًا قابلًا للقياس')

  // The author resolves the comment that lost its place.
  await author.getByTestId('unanchored-comments').getByTestId('comment-resolve').click()
  await expect(author.getByTestId('unanchored-comments')).toHaveCount(0)
})
