import { expect, test } from '@playwright/test'

import { emailTo, PASSWORD as PASSWORD_E2E, passwordLink, signIn } from './helpers'

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

// From the review of phase 8: a set-password link opened where someone is already signed in leads to the sign-in
// form; and an admin who lowers their own role sees the menu follow at once.
test('a link opened while signed in leads to the sign-in form, and a role one lowers oneself takes effect', async ({
  browser,
}) => {
  test.setTimeout(120_000)
  const address = `second-admin-${`${Date.now()}`.slice(-7)}@example.com`
  const admin = await signIn(browser, 'multi@example.com')
  await admin.getByTestId('nav-members').click()
  await admin.getByTestId('member-email').fill(address)
  await admin.getByTestId('member-new-role').selectOption('admin')
  const sentAfter = Date.now() - 1000
  await admin.getByTestId('member-add-submit').click()
  await expect(admin.getByTestId('member-added')).toContainText(address)

  // The admin's own browser, still signed in, opens the new person's invitation.
  await admin.goto(passwordLink(await emailTo(address, sentAfter)))
  await admin.getByTestId('password-new').fill(PASSWORD)
  await admin.getByTestId('password-again').fill(PASSWORD)
  await admin.getByRole('button', { name: 'حفظ كلمة المرور' }).click()
  await expect(admin.getByTestId('password-set')).toBeVisible()
  await admin.getByTestId('password-to-sign-in').click()
  await expect(admin.locator('input[name="email"]')).toBeVisible()

  // The new admin signs in there, and makes themselves an author: the admin's pages go without a reload.
  await admin.locator('input[name="email"]').fill(address)
  await admin.locator('input[name="password"]').fill(PASSWORD)
  await admin.locator('button[type="submit"]').click()
  await admin.getByTestId('nav-members').click()
  const own = admin.locator(`[data-testid="member"][data-email="${address}"]`)
  await own.getByTestId('member-role').selectOption('author')
  await expect(admin.getByTestId('nav-members')).toHaveCount(0)
  await admin.getByRole('link', { name: 'حراك' }).click() // within the app, no reload
  await expect(admin.getByTestId('current-role')).toHaveText('مؤلف')
})

// D90 (F7 of the phase 8 review): joining takes the person's acceptance. The admin invites an account of another
// organization and sees its email alone; an invitation not answered can be cancelled; the person joins by accepting.
test('an existing account is invited, seen by its email alone, and joins only by accepting', async ({ browser }) => {
  test.setTimeout(120_000)
  const admin = await signIn(browser, 'multi@example.com')
  await admin.getByTestId('nav-members').click()
  const invite = async () => {
    await admin.getByTestId('member-email').fill('guest@example.com')
    await admin.getByTestId('member-new-role').selectOption('reviewer')
    await admin.getByTestId('member-add-submit').click()
    await expect(admin.getByTestId('member-added')).toContainText('guest@example.com')
  }
  const row = admin.locator('[data-testid="member"][data-email="guest@example.com"]')
  await invite()
  await expect(row).toHaveAttribute('data-status', 'invited')
  await expect(row).not.toContainText('ضيف من مؤسسة السلامة')
  await row.getByTestId('member-cancel').click()
  await expect(row).toHaveCount(0)
  await invite()
  await expect(row.getByTestId('member-invited')).toBeVisible()

  // The guest signs in to their own organization and finds the invitation there.
  const guest = await (await browser.newContext()).newPage()
  await guest.goto('/login')
  await guest.locator('input[name="email"]').fill('guest@example.com')
  await guest.locator('input[name="password"]').fill(PASSWORD_E2E)
  await guest.locator('button[type="submit"]').click()
  await expect(guest.getByTestId('current-organization')).toHaveText('أكاديمية السلامة')
  const invitation = guest.getByTestId('invitation')
  await expect(invitation).toContainText('مركز التدريب المهني')
  await guest.screenshot({ path: 'e2e/screenshots/98-invitation-ar.png', fullPage: true })
  await invitation.getByTestId('invitation-accept').click()
  await expect(guest.getByTestId('invitations')).toHaveCount(0)
  await guest.getByTestId('organization-switcher').selectOption({ label: 'مركز التدريب المهني' })
  await expect(guest.getByTestId('current-organization')).toHaveText('مركز التدريب المهني')
  await guest.getByRole('link', { name: 'حراك' }).click()
  await expect(guest.getByTestId('current-role')).toHaveText('مراجع')

  // Now a member: the admin sees the name the person keeps.
  await admin.reload()
  await expect(row).toHaveAttribute('data-status', 'member')
  await expect(row).toContainText('ضيف من مؤسسة السلامة')
})
