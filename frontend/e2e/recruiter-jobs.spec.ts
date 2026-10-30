import { expect, type Page, test } from '@playwright/test'
import {
  createE2eStaff,
  E2E_STAFF_PASSWORD,
  embedQueuedWithMockedOpenAI,
  jobEmbeddingCount,
  uniqueE2eEmail,
} from './support/backend.ts'

const adminEmail = uniqueE2eEmail('jobs-admin')
const recruiterEmail = uniqueE2eEmail('jobs-recruiter')
const NEW_PASSWORD = 'e2e-recruiter-new-password-1'
const jobTitle = `E2E Platform Engineer ${Date.now()}`

async function signIn(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

test.describe('recruiter accounts and job roles', () => {
  test.beforeAll(() => {
    createE2eStaff(adminEmail, 'admin', 'E2E Jobs Admin')
  })

  test('admin adds a recruiter, who changes the password, posts a job and sees it embedded', async ({ page }) => {
    // 1. The admin signs in and opens the staff list.
    await signIn(page, adminEmail, E2E_STAFF_PASSWORD)
    await expect(page.getByRole('heading', { level: 1, name: 'Candidates' })).toBeVisible()
    await page.getByRole('link', { name: 'Users' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Staff accounts' })).toBeVisible()

    // 2. Add a recruiter with a generated temporary password.
    await page.getByRole('button', { name: 'Add recruiter' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Email').fill(recruiterEmail)
    await dialog.getByLabel('Full name').fill('E2E Jobs Recruiter')
    await dialog.getByRole('button', { name: 'Generate' }).click()
    const temporaryPassword = await dialog.getByLabel(/Temporary password/).inputValue()
    expect(temporaryPassword).toHaveLength(16)
    await dialog.getByRole('button', { name: 'Add account' }).click()
    const row = page.getByRole('row').filter({ hasText: recruiterEmail })
    await expect(row).toBeVisible()
    await expect(row.getByText(/must change password/i)).toBeVisible()

    // 3. The recruiter is held on the change-password page.
    await page.getByRole('button', { name: 'Sign out' }).click()
    await signIn(page, recruiterEmail, temporaryPassword)
    await expect(page.getByRole('heading', { name: 'Change your password' })).toBeVisible()
    await expect(page).toHaveURL(/\/account\/password/)
    await page.goto('/admin/candidates')
    await expect(page).toHaveURL(/\/account\/password/)

    // 4. Changing it unlocks the app. Recruiters get Jobs but not Users.
    await page.getByLabel(/^Current password/).fill(temporaryPassword)
    await page.getByLabel(/^New password/).fill(NEW_PASSWORD)
    await page.getByLabel(/^Confirm new password/).fill(NEW_PASSWORD)
    await page.getByRole('button', { name: 'Change password' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Candidates' })).toBeVisible()
    const nav = page.getByRole('navigation', { name: 'Main' })
    await expect(nav.getByRole('link', { name: 'Jobs', exact: true })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Users' })).toHaveCount(0)
    await page.goto('/admin/users')
    await expect(page.getByText('Only admins can manage staff accounts.')).toBeVisible()

    // 5. Add a job.
    await page.goto('/jobs')
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Add job' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Add job' })).toBeVisible()
    await page.getByLabel('Job title').fill(jobTitle)
    await page.getByLabel(/^City/).fill('Berlin')
    await page.getByLabel(/^Country/).selectOption({ label: 'Germany' })
    await page.getByLabel(/^Minimum years/).fill('3')
    // The added-skills list is labelled "Must-have skills added", so target the text box.
    const mustHaves = page.getByRole('textbox', { name: /^Must-have skills/ })
    await mustHaves.fill('python')
    await mustHaves.press('Enter')
    await mustHaves.fill('postgresql')
    await mustHaves.press('Enter')
    await page
      .getByLabel('Job description')
      .fill('You will design and run backend services that match candidates to open roles, and own their reliability end to end.')
    await page.getByRole('button', { name: 'Add job' }).click()
    await expect(page.getByRole('heading', { level: 1, name: jobTitle })).toBeVisible()
    await expect(page.getByText('Draft', { exact: true })).toBeVisible()
    await expect(page.getByText('Queued', { exact: true })).toBeVisible()
    const jobId = page.url().split('/').pop() ?? ''

    // 6. It is in the list.
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Jobs', exact: true }).click()
    await expect(page.getByRole('link', { name: jobTitle, exact: true })).toBeVisible()

    // 7. The worker embeds it (OpenAI mocked in the child process).
    embedQueuedWithMockedOpenAI()
    expect(jobEmbeddingCount(jobId)).toBe(1)
    await page.goto(`/jobs/${jobId}`)
    await expect(page.getByText('Ready', { exact: true })).toBeVisible()
  })
})
