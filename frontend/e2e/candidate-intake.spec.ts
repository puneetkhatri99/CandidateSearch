import { expect, type Page, test } from '@playwright/test'
import { uniqueE2eEmail } from './support/backend.ts'

async function fillValidProfile(page: Page, email: string) {
  await page.getByLabel('Full name').fill('Playwright Tester')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Phone').fill('+91 98765 43210')
  await page.getByLabel('City').fill('Bengaluru')
  await page.getByLabel('Country').selectOption('IN')
  await page.getByLabel('GitHub profile').fill('https://github.com/playwright-tester')

  await page.getByLabel('Headline / current title').fill('Senior QA Engineer')
  await page.getByLabel('Total years of experience').fill('6.5')
  const skills = page.getByRole('textbox', { name: 'Skills' })
  for (const skill of ['Playwright', 'TypeScript', 'playwright']) {
    await skills.fill(skill)
    await skills.press('Enter')
  }
  await page
    .getByLabel('Professional summary')
    .fill('QA engineer automating end-to-end tests for web applications and APIs at scale.')

  await page.getByRole('button', { name: 'Add experience' }).click()
  await page.getByLabel('Company').fill('Acme')
  await page.getByRole('textbox', { name: 'Title', exact: true }).fill('QA Engineer')
  await page.getByLabel('Start month').fill('2021-03')
  await page.getByLabel('I currently work here').check()

  await page.getByLabel('Remote').check()
  await page.getByLabel('Notice period (days)').fill('30')
  await page.getByLabel(/I agree that my data is stored/).check()
}

test.describe('candidate intake', () => {
  test('a candidate submits the form and sees the success screen', async ({ page }) => {
    await page.goto('/apply')
    await expect(page.getByRole('heading', { level: 1, name: 'Create your candidate profile' })).toBeVisible()

    await fillValidProfile(page, uniqueE2eEmail('happy'))
    // Duplicate tags are folded case-insensitively before submit.
    await expect(page.getByRole('list', { name: 'Skills added' }).getByRole('listitem')).toHaveCount(2)

    const responsePromise = page.waitForResponse((r) => r.url().endsWith('/api/v1/candidates'))
    await page.getByRole('button', { name: 'Submit profile' }).click()
    const response = await responsePromise

    expect(response.status()).toBe(201)
    expect(Object.keys(await response.json()).sort()).toEqual(['created_at', 'id'])
    await expect(page.getByRole('heading', { name: 'Thanks, your profile was received' })).toBeVisible()
  })

  test('a duplicate email (different case) shows the already-registered message', async ({ page }) => {
    const email = uniqueE2eEmail('dup')

    await page.goto('/apply')
    await fillValidProfile(page, email)
    await page.getByRole('button', { name: 'Submit profile' }).click()
    await expect(page.getByRole('heading', { name: 'Thanks, your profile was received' })).toBeVisible()

    await page.goto('/apply')
    await fillValidProfile(page, email.toUpperCase())
    await page.getByRole('button', { name: 'Submit profile' }).click()

    await expect(page.getByText(/A profile with this email already exists/)).toBeVisible()
    await expect(page.getByLabel('Email')).toHaveAttribute('aria-invalid', 'true')
    await expect(page.getByLabel('Email')).toBeFocused()
    await expect(page.getByRole('heading', { name: 'Thanks, your profile was received' })).toHaveCount(0)
  })

  test('submitting an empty form shows errors and focuses the first invalid field', async ({ page }) => {
    let apiCalls = 0
    page.on('request', (r) => {
      if (r.url().includes('/api/v1/candidates')) apiCalls += 1
    })

    await page.goto('/apply')
    await page.getByRole('button', { name: 'Submit profile' }).click()

    await expect(page.getByText('Full name must be at least 2 characters.')).toBeVisible()
    await expect(page.getByLabel('Full name')).toBeFocused()
    // Screen readers must announce the consent error with the checkbox.
    await expect(page.getByLabel(/I agree that my data is stored/)).toHaveAccessibleDescription(
      'You must agree to the privacy notice to continue.',
    )
    expect(apiCalls).toBe(0)
  })

  test('the form fits a phone-sized viewport without horizontal scrolling', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 })
    await page.goto('/apply')

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })
})
