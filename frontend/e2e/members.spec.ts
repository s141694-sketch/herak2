import { expect, test } from '@playwright/test'

import { emailTo, passwordLink, signIn } from './helpers'

// D87 (spec 2.1: the training manager runs the space and its users): the admin adds a new person by email with a
// role; the invitation's link lets them choose a password and sign in; the admin changes their role; a forgotten
// password gets a new link. The emails are read from where the backend keeps them in these tests.
const PASSWORD = 'invited-person-password-1'

test('an admin invites a new person, who chooses a password, signs in, and later resets it', async ({ browser }) => {
  test.setTimeout(120_000)
  const stamp = `${Date.now()}`.slice(-7)
  const address = `invited-${stamp}@example.com`
  const admin = await signIn(browser, 'multi@example.com')
  await admin.getByTestId('nav-members').click()
  await admin.getByTestId('member-email').fill(address)
  await admin.getByTestId('member-name').fill('ضيف الاختبار')
  await admin.getByTestId('member-new-role').selectOption('author')
  const sentAfter = Date.now() - 1000
  await admin.getByTestId('member-add-submit').click()
  await expect(admin.getByTestId('member-added')).toContainText(address)
  const row = admin.locator(`[data-testid="member"][data-email="${address}"]`)
  await expect(row.getByTestId('member-role')).toHaveValue('author')
  await admin.screenshot({ path: 'e2e/screenshots/97-members-ar.png', fullPage: true })

  // The invitation's link, in a browser of the new person's own.
  const invitation = await emailTo(address, sentAfter)
  expect(invitation).toContain('مركز التدريب المهني')
  const person = await (await browser.newContext()).newPage()
  await person.goto(passwordLink(invitation))
  await person.getByTestId('password-new').fill(PASSWORD)
  await person.getByTestId('password-again').fill(PASSWORD)
  await person.getByRole('button', { name: 'حفظ كلمة المرور' }).click()
  await expect(person.getByTestId('password-set')).toBeVisible()
  // The link works once.
  await person.goto(passwordLink(invitation))
  await person.getByTestId('password-new').fill('another-password-22')
  await person.getByTestId('password-again').fill('another-password-22')
  await person.getByRole('button', { name: 'حفظ كلمة المرور' }).click()
  await expect(person.getByTestId('password-error')).toContainText('لم يعد هذا الرابط صالحًا')

  await person.getByTestId('password-to-sign-in').click()
  await person.locator('input[name="email"]').fill(address)
  await person.locator('input[name="password"]').fill(PASSWORD)
  await person.locator('button[type="submit"]').click()
  await expect(person.getByTestId('current-organization')).toHaveText('مركز التدريب المهني')
  await expect(person.getByTestId('current-role')).toHaveText('مؤلف')

  // The admin makes them a reviewer: the role holds at once.
  await row.getByTestId('member-role').selectOption('reviewer')
  await expect(row.getByTestId('member-role')).toHaveValue('reviewer')
  await person.reload()
  await expect(person.getByTestId('current-role')).toHaveText('مراجع')

  // Forgotten: a new link from the sign-in page.
  const forgetful = await (await browser.newContext()).newPage()
  await forgetful.goto('/login')
  await forgetful.getByTestId('login-forgot').click()
  await forgetful.getByTestId('password-email').fill(address)
  const askedAfter = Date.now() - 1000
  await forgetful.getByRole('button', { name: 'أرسل الرابط' }).click()
  await expect(forgetful.getByTestId('password-link-sent')).toBeVisible()
  await forgetful.goto(passwordLink(await emailTo(address, askedAfter)))
  await forgetful.getByTestId('password-new').fill('a-new-password-333')
  await forgetful.getByTestId('password-again').fill('a-new-password-333')
  await forgetful.getByRole('button', { name: 'حفظ كلمة المرور' }).click()
  await expect(forgetful.getByTestId('password-set')).toBeVisible()

})
