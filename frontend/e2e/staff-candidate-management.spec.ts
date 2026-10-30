import { expect, type Page, test } from '@playwright/test'
import { createE2eStaff, E2E_STAFF_PASSWORD, uniqueE2eEmail } from './support/backend.ts'

const API = 'http://localhost:8011/api/v1'

const adminEmail = uniqueE2eEmail('admin')
const recruiterEmail = uniqueE2eEmail('recruiter')

function randomLetters(length: number): string {
  return Array.from({ length }, () => String.fromCharCode(97 + Math.floor(Math.random() * 26))).join('')
}

async function signIn(page: Page, email: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(E2E_STAFF_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Candidates' })).toBeVisible()
}

/** Each seeded candidate lives in a city of its own, so the City filter finds just that one. */
async function seedCandidate(page: Page, fullName: string, email: string, city: string): Promise<void> {
  const response = await page.request.post(`${API}/candidates`, {
    data: {
      full_name: fullName,
      email,
      phone: '+91 98765 43210',
      city,
      country_code: 'IN',
      linkedin_url: '',
      github_url: '',
      portfolio_url: '',
      headline: 'Original Headline Engineer',
      years_experience: 4,
      skills: ['Python', 'FastAPI'],
      summary: 'Backend engineer building APIs and data pipelines for fintech products at scale.',
      experiences: [],
      educations: [],
      desired_roles: ['Backend Engineer'],
      work_modes: ['remote'],
      open_to_relocation: false,
      consent: true,
    },
  })
  expect(response.status()).toBe(201)
}

test.describe('staff candidate management', () => {
  test.beforeAll(() => {
    createE2eStaff(adminEmail, 'admin', 'E2E Admin')
    createE2eStaff(recruiterEmail, 'recruiter', 'E2E Recruiter')
  })

  test('admin: sign in, search, edit, delete, sign out, then the page is protected again', async ({ page }) => {
    const token = randomLetters(10)
    const fullName = `Zq${token} Tester`
    const email = uniqueE2eEmail(token)
    const city = `Zqcity ${token}`
    await seedCandidate(page, fullName, email, city)

    await signIn(page, adminEmail)

    // Filter by city (case-insensitive; the table should narrow to the one seeded candidate).
    await page.getByRole('textbox', { name: 'City' }).fill(city.toUpperCase())
    const table = page.getByRole('table')
    await expect(table.getByRole('link', { name: fullName, exact: true })).toBeVisible()
    await expect(table.getByRole('row')).toHaveCount(2) // header + 1 result

    // Open the profile.
    await table.getByRole('link', { name: fullName, exact: true }).click()
    await expect(page.getByRole('heading', { level: 1, name: fullName })).toBeVisible()
    await expect(page.getByText('Original Headline Engineer')).toBeVisible()

    // Edit the headline and save.
    await page.getByRole('button', { name: 'Edit', exact: true }).click()
    const headline = page.getByLabel('Headline / current title')
    await expect(headline).toHaveValue('Original Headline Engineer')
    await headline.fill('Principal Platform Engineer')
    const saved = page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().includes('/admin/candidates/'))
    await page.getByRole('button', { name: 'Save changes' }).click()
    expect((await saved).status()).toBe(200)
    await expect(page.getByText('Principal Platform Engineer')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Edit', exact: true })).toBeVisible()

    // Delete (admin only) after confirming.
    await page.getByRole('button', { name: 'Delete', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: `Delete ${fullName}?` })).toBeVisible()
    await dialog.getByRole('button', { name: 'Delete permanently' }).click()
    await expect(page).toHaveURL(/\/admin\/candidates$/)

    // Gone from the list.
    await page.getByRole('textbox', { name: 'City' }).fill(city)
    await expect(page.getByText('No candidates match your search.')).toBeVisible()

    // Sign out; the protected page now redirects to login.
    await page.getByRole('button', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/login/)
    await page.goto('/admin/candidates')
    await expect(page).toHaveURL(/\/login\?next=%2Fadmin%2Fcandidates/)
    await expect(page.getByRole('heading', { name: 'Staff sign in' })).toBeVisible()
  })

  test('visitors without a session are redirected from every admin page', async ({ page }) => {
    for (const path of ['/admin/candidates', '/admin/candidates/new', '/admin/candidates/00000000-0000-0000-0000-000000000000']) {
      await page.goto(path)
      await expect(page).toHaveURL(/\/login\?next=/)
    }
    const api = await page.request.get(`${API}/admin/candidates`)
    expect(api.status()).toBe(401)
  })

  test('wrong password shows the generic error and stays on the login page', async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel('Email').fill(adminEmail)
    await page.getByLabel('Password').fill('not-the-password-123')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('alert')).toContainText('Invalid email or password')
    await expect(page).toHaveURL(/\/login/)
  })

  test('login ?next= only honours same-site paths (no open redirect)', async ({ page }) => {
    await page.goto('/login?next=//evil.example/steal')
    await page.getByLabel('Email').fill(adminEmail)
    await page.getByLabel('Password').fill(E2E_STAFF_PASSWORD)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page).toHaveURL(/localhost:5181\/admin\/candidates$/)
    await page.getByRole('button', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/login/)
  })

  test('recruiter can open and edit profiles but has no Delete button and the API refuses it', async ({ page }) => {
    const token = randomLetters(10)
    const fullName = `Zr${token} Tester`
    const city = `Zrcity ${token}`
    await seedCandidate(page, fullName, uniqueE2eEmail(token), city)

    await signIn(page, recruiterEmail)
    await page.getByRole('textbox', { name: 'City' }).fill(city)
    await page.getByRole('table').getByRole('link', { name: fullName, exact: true }).click()
    await expect(page.getByRole('heading', { level: 1, name: fullName })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Edit', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(0)

    const id = page.url().split('/').pop()
    const status = await page.evaluate(async (candidateId) => {
      const response = await fetch(`/api/v1/admin/candidates/${candidateId}`, {
        method: 'DELETE',
        headers: { 'X-Requested-With': 'fetch' },
      })
      return response.status
    }, id)
    expect(status).toBe(403)
    await expect(page.getByRole('heading', { level: 1, name: fullName })).toBeVisible()
  })
})
