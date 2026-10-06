import { type Browser, expect, type Page, test } from '@playwright/test'

import { keycloakSignIn, PASSWORD, totp } from './helpers'

// Phase 6 acceptance (spec 8.1 item 6) on the real Keycloak (infra/keycloak, realm vtc): an admin sets up the
// organization's provider and its tests in the interface, then the first sign-in, a domain that is not verified,
// enforcement, and the emergency account. The seed starts the institute with nothing set up on every run.

const KEYCLOAK = process.env.KEYCLOAK_URL ?? 'http://localhost:8180'

async function passwordPage(browser: Browser, email: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage()
  await page.goto('/login')
  await page.locator('input[name="email"]').fill(email)
  await page.locator('input[name="password"]').fill(PASSWORD)
  await page.locator('button[type="submit"]').click()
  return page
}

async function throughOrganization(browser: Browser, email: string, username: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage()
  await page.goto('/login')
  await page.locator('input[name="email"]').fill(email)
  await page.getByTestId('login-sso').click()
  await page.waitForURL(new RegExp(`^${KEYCLOAK}/realms/vtc/`))
  await keycloakSignIn(page, username)
  return page
}

test('an admin sets up single sign-on, members sign in through it, and enforcement keeps the emergency account', async ({ browser }) => {
  test.setTimeout(180_000)

  // The admin turns on their own second factor first: the emergency account must have one (spec 7.2).
  const admin = await passwordPage(browser, 'sso-admin@example.com')
  await expect(admin.getByTestId('current-organization')).toHaveText('معهد حرفة')
  await admin.getByTestId('user-name').click()
  await admin.getByTestId('mfa-start').click()
  const secret = (await admin.getByTestId('mfa-secret').textContent())!.trim()
  await admin.getByTestId('mfa-confirm-code').fill(totp(secret))
  await admin.getByTestId('mfa-confirm').click()
  await expect(admin.getByTestId('mfa-status')).toHaveAttribute('data-enabled', 'true')

  // The provider: saved, connection tested, then a test sign-in through Keycloak.
  await admin.goto('/settings/security')
  await expect(admin.getByTestId('sso-domain').filter({ hasText: 'vtc.test' })).toHaveAttribute('data-verified', 'true')
  await admin.getByTestId('sso-issuer').fill(`${KEYCLOAK}/realms/vtc`)
  await admin.getByTestId('sso-client-id').fill('harak2')
  await admin.getByTestId('sso-client-secret').fill('vtc-test-client-secret')
  await admin.getByTestId('sso-provider-save').click()
  await admin.getByTestId('sso-test-connection-run').click()
  await expect(admin.getByTestId('sso-test-connection')).toHaveAttribute('data-ok', 'true')
  await admin.getByTestId('sso-test-login-run').click()
  await admin.waitForURL(new RegExp(`^${KEYCLOAK}/realms/vtc/`))
  await keycloakSignIn(admin, 'hamed')
  await expect(admin.getByTestId('sso-test-result')).toHaveAttribute('data-result', 'ok')
  await expect(admin.getByTestId('sso-test-login')).toHaveAttribute('data-ok', 'true')
  await admin.screenshot({ path: 'e2e/screenshots/90-security-settings-ar.png', fullPage: true })

  // Enabled: the first sign-in through the provider makes a member pending an assignment.
  await admin.getByTestId('sso-enabled').click() // the box follows the server's answer
  await expect(admin.getByTestId('sso-enabled')).toBeChecked()
  const noura = await throughOrganization(browser, 'noura@vtc.test', 'noura')
  await expect(noura.getByTestId('current-organization')).toHaveText('معهد حرفة')
  await expect(noura.getByTestId('current-role')).toHaveText('بانتظار التعيين')

  // A domain no organization verified has no single sign-on.
  const outsider = await (await browser.newContext()).newPage()
  await outsider.goto('/login')
  await outsider.locator('input[name="email"]').fill('outsider@elsewhere.test')
  await outsider.getByTestId('login-sso').click()
  await expect(outsider.getByTestId('login-error')).toHaveText('لا يوجد دخول موحد لهذا البريد. ادخل بكلمة المرور.')

  // The provider's page speaks the interface's language: in English, Keycloak's own page is in English too.
  const english = await (await browser.newContext()).newPage()
  await english.goto('/login')
  await english.getByRole('button', { name: 'اللغة' }).click()
  await expect(english.locator('html')).toHaveAttribute('dir', 'ltr')
  await english.locator('input[name="email"]').fill('noura@vtc.test')
  await english.getByTestId('login-sso').click()
  await english.waitForURL(new RegExp(`^${KEYCLOAK}/realms/vtc/`))
  await expect(english.locator('html')).toHaveAttribute('lang', 'en')
  await keycloakSignIn(english, 'noura')
  await expect(english.getByTestId('current-role')).toHaveText('Pending assignment')

  // Enforced, with the admin as the emergency account.
  await admin.getByTestId('sso-emergency').selectOption({ label: 'سالم المعمري' })
  await expect(admin.getByTestId('sso-emergency').locator('option:checked')).toHaveText('سالم المعمري')
  await admin.getByTestId('sso-enforced').click()
  await expect(admin.getByTestId('sso-enforced')).toBeChecked()

  // A member's password no longer opens the organization; the provider does.
  const hamedPassword = await passwordPage(browser, 'hamed@vtc.test')
  await expect(hamedPassword.getByTestId('login-error')).toHaveText(
    'مؤسستك تفرض الدخول عبر مزوّد هويتها. استخدم «الدخول عبر مؤسستك».',
  )
  const hamed = await throughOrganization(browser, 'hamed@vtc.test', 'hamed')
  await expect(hamed.getByTestId('current-organization')).toHaveText('معهد حرفة')
  await expect(hamed.getByTestId('current-role')).toHaveText('مؤلف')

  // The emergency account still signs in with its password and its code.
  const emergency = await passwordPage(browser, 'sso-admin@example.com')
  await expect(emergency.getByTestId('mfa-step')).toBeVisible()
  await emergency.getByTestId('mfa-code').fill(totp(secret, 1))
  await emergency.getByRole('button', { name: 'تحقق' }).click()
  await expect(emergency.getByTestId('current-organization')).toHaveText('معهد حرفة')
})

test('sign-in refusals are explained in Arabic and in English', async ({ browser }) => {
  const page = await (await browser.newContext()).newPage()
  await page.goto('/login?sso_error=sso_domain_not_allowed')
  await expect(page.getByTestId('login-error')).toHaveText(
    'بريدك ليس في نطاق موثّق لهذه المؤسسة، فلا يمكن الدخول به. استخدم بريد عملك، أو راجع مدير مؤسستك.',
  )
  await page.getByRole('button', { name: 'اللغة' }).click()
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr')
  await expect(page.getByTestId('login-error')).toHaveText(
    "Your email is not in a domain this organization verified, so it cannot be used to sign in. Use your work email, or ask your organization's admin.",
  )
  await page.goto('/login?sso_error=provider_unavailable')
  await expect(page.getByTestId('login-error')).toContainText('the emergency account signs in with a password')
  await page.screenshot({ path: 'e2e/screenshots/91-login-provider-down-en.png', fullPage: true })
})
