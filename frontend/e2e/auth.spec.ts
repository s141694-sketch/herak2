import { expect, type Page, test } from '@playwright/test'

// Task 1.9 acceptance: sign in through the browser in Arabic and in English.
const PASSWORD = process.env.E2E_PASSWORD ?? 'harak-e2e-password'

async function signIn(page: Page, email: string, password = PASSWORD) {
  await page.getByRole('textbox', { name: /البريد الإلكتروني|Email/ }).fill(email)
  await page.locator('input[name="password"]').fill(password)
  await page.locator('button[type="submit"]').click()
}

const shot = (page: Page, name: string) => page.screenshot({ path: `e2e/screenshots/${name}.png`, fullPage: true })

test('Arabic: the login page is RTL and signing in shows the organization and role in Arabic', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar')
  await expect(page.getByRole('heading', { name: 'تسجيل الدخول' })).toBeVisible()
  await shot(page, '01-login-ar')

  await signIn(page, 'author@example.com')
  await expect(page.getByTestId('home')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'مرحبًا، سارة الحارثية' })).toBeVisible()
  await expect(page.getByTestId('current-organization')).toHaveText('مركز التدريب المهني')
  await expect(page.getByTestId('current-role')).toHaveText('مؤلف')
  await shot(page, '02-home-ar')
})

test('English: switching language flips the layout to LTR and signing in works in English', async ({ page }) => {
  await page.goto('/login')
  await page.getByTestId('language-toggle').click()
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await shot(page, '03-login-en')

  await signIn(page, 'author@example.com')
  await expect(page.getByTestId('current-role')).toHaveText('Author')
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()

  // The choice survives a reload.
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr')
  await expect(page.getByTestId('current-role')).toHaveText('Author')
  await shot(page, '04-home-en')
})

test('a wrong password shows a translated error in both languages', async ({ page }) => {
  await page.goto('/login')
  await signIn(page, 'author@example.com', 'wrong-password')
  await expect(page.getByTestId('login-error')).toHaveText('البريد الإلكتروني أو كلمة المرور غير صحيحة. تحقق منهما وحاول مرة أخرى.')
  await page.getByTestId('language-toggle').click()
  await expect(page.getByTestId('login-error')).toHaveText('The email or password is incorrect. Check them and try again.')
  await expect(page).toHaveURL(/\/login$/)
})

test('a member of two organizations chooses one, switches, and the choice persists', async ({ page }) => {
  await page.goto('/login')
  await signIn(page, 'multi@example.com')
  await expect(page.getByTestId('choose-organization')).toBeVisible()
  await shot(page, '05-choose-organization-ar')
  await page.getByRole('button', { name: /أكاديمية السلامة/ }).click()
  await expect(page.getByTestId('current-organization')).toHaveText('أكاديمية السلامة')
  await expect(page.getByTestId('current-role')).toHaveText('مراجع')

  await page.getByTestId('organization-switcher').selectOption({ label: 'مركز التدريب المهني' })
  await expect(page.getByTestId('current-organization')).toHaveText('مركز التدريب المهني')
  await expect(page.getByTestId('current-role')).toHaveText('مدير التدريب')

  await page.reload()
  await expect(page.getByTestId('current-organization')).toHaveText('مركز التدريب المهني')
  await shot(page, '06-switched-ar')
})

test('a pending member sees that no role has been assigned', async ({ page }) => {
  await page.goto('/login')
  await signIn(page, 'pending@example.com')
  await expect(page.getByTestId('current-role')).toHaveText('بانتظار التعيين')
  await expect(page.getByText('لم يُمنح حسابك دورًا في هذه المؤسسة بعد', { exact: false })).toBeVisible()
})

test('signing out returns to the login page and protects the app', async ({ page }) => {
  await page.goto('/login')
  await signIn(page, 'author@example.com')
  await expect(page.getByTestId('home')).toBeVisible()
  await page.getByTestId('logout').click()
  await expect(page).toHaveURL(/\/login$/)
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
})
