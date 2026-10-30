import { expect, type Page, test } from '@playwright/test'
import { createE2eStaff, E2E_STAFF_PASSWORD, uniqueE2eEmail } from './support/backend.ts'

const API = 'http://localhost:8011/api/v1'
const DEFAULT_LIMIT = '5.00'

const adminEmail = uniqueE2eEmail('ai-admin')
const recruiterEmail = uniqueE2eEmail('ai-recruiter')

async function signIn(page: Page, email: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(E2E_STAFF_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Candidates' })).toBeVisible()
}

test.describe('AI spending page', () => {
  test.beforeAll(() => {
    createE2eStaff(adminEmail, 'admin', 'E2E AI Admin')
    createE2eStaff(recruiterEmail, 'recruiter', 'E2E AI Recruiter')
  })

  test('admin changes the limit and sees it, then the default is restored', async ({ page }) => {
    await signIn(page, adminEmail)
    try {
      await page.getByRole('link', { name: 'AI spending' }).click()
      await expect(page.getByRole('heading', { level: 1, name: 'AI spending' })).toBeVisible()

      await page.getByRole('button', { name: 'Edit limit' }).click()
      const dialog = page.getByRole('dialog')
      await dialog.getByLabel('Limit (USD)').fill('7.50')
      const saved = page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith('/ai-usage/budget'))
      await dialog.getByRole('button', { name: 'Save limit' }).click()
      expect((await saved).status()).toBe(200)

      await expect(page.getByText(/of \$7\.50/)).toBeVisible()
      await page.reload()
      await expect(page.getByText(/of \$7\.50/)).toBeVisible()
    } finally {
      // The budget is a single shared row: always put it back for other runs.
      await page.request.put(`${API}/ai-usage/budget`, {
        data: { limit_usd: DEFAULT_LIMIT },
        headers: { 'X-Requested-With': 'fetch' },
      })
    }
  })

  test('recruiter sees the page but not the Edit limit action', async ({ page }) => {
    await signIn(page, recruiterEmail)

    await page.getByRole('link', { name: 'AI spending' }).click()

    await expect(page.getByRole('heading', { level: 1, name: 'AI spending' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Lifetime budget' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Edit limit' })).toHaveCount(0)
  })
})