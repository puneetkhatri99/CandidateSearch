import { expect, type Page, test } from '@playwright/test'
import { createE2eStaff, E2E_STAFF_PASSWORD, uniqueE2eEmail } from './support/backend.ts'

/**
 * Visual and a11y QA for the plain black/white design system with blue, red and green highlights. Screenshots go to SCREEN_DIR (set DESIGN_QA_DIR);
 * without it the screenshots are skipped and only the assertions run.
 */
const SCREEN_DIR = process.env.DESIGN_QA_DIR
const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'phone', width: 400, height: 860 },
] as const

const adminEmail = uniqueE2eEmail('design-admin')
const runTag = Date.now().toString(36)
const nameFor = (viewport: string) => `Design Candidate ${runTag} ${viewport}`
const longName = 'Bartholomew Maximilian Featherstonehaugh-Wolfeschlegelstein'

async function seedCandidate(page: Page, name: string, email: string, headline: string, city: string) {
  await page.goto('/apply')
  await page.getByLabel('Full name').fill(name)
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Phone').fill('+91 98765 43210')
  await page.getByLabel('City').fill(city)
  await page.getByLabel('Country').selectOption('IN')
  await page.getByLabel('Headline / current title').fill(headline)
  await page.getByLabel('Total years of experience').fill('6.5')
  const skills = page.getByRole('textbox', { name: 'Skills' })
  for (const skill of ['Playwright', 'TypeScript', 'Kubernetes', 'PostgreSQL', 'Distributed systems']) {
    await skills.fill(skill)
    await skills.press('Enter')
  }
  await page.getByLabel('Professional summary').fill('QA engineer automating end-to-end tests for web applications and APIs at scale.')
  await page.getByLabel('Remote').check()
  await page.getByLabel('Notice period (days)').fill('30')
  await page.getByLabel(/I agree that my data is stored/).check()
  const done = page.waitForResponse((r) => r.url().endsWith('/api/v1/candidates') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Submit profile' }).click()
  expect((await done).status()).toBe(201)
}

async function overflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
}

test.describe('Design QA', () => {
  test.beforeAll(() => createE2eStaff(adminEmail, 'admin', 'E2E Design Admin'))

  for (const vp of VIEWPORTS) {
    test(`pages render without overflow at ${vp.name}`, async ({ page }) => {
      test.setTimeout(120_000)
      const firstName = nameFor(vp.name)
      await page.setViewportSize({ width: vp.width, height: vp.height })
      const hosts = new Set<string>()
      page.on('request', (r) => hosts.add(new URL(r.url()).host))
      const overflows: string[] = []
      const shot = async (name: string, fullPage = true) => {
        const o = await overflow(page)
        if (o > 0) overflows.push(`${name}: ${o}px`)
        if (SCREEN_DIR) await page.screenshot({ path: `${SCREEN_DIR}\\${vp.name}-${name}.png`, fullPage })
      }

      await page.goto('/login')
      await expect(page.getByRole('heading', { name: 'Staff sign in' })).toBeVisible()
      await shot('01-login')
      await page.getByLabel('Email').fill('nobody@example.com')
      await page.getByLabel('Password').fill('wrong-password-123')
      await page.getByRole('button', { name: 'Sign in' }).click()
      await expect(page.getByRole('alert')).toBeVisible()
      await shot('02-login-error')

      await page.goto('/apply')
      await shot('03-intake-empty')
      await page.getByRole('button', { name: 'Submit profile' }).click()
      await expect(page.locator('[aria-invalid="true"]').first()).toBeVisible()
      await shot('04-intake-errors')

      await page.goto('/privacy')
      await shot('05-privacy')
      await page.goto('/nope-not-a-page')
      await shot('06-404')

      // A city only this run uses, so the City filter finds exactly these two.
      const city = `Designville ${runTag} ${vp.name}`
      await seedCandidate(page, firstName, uniqueE2eEmail('d1'), 'Senior QA Engineer', city)
      await seedCandidate(page, longName, uniqueE2eEmail('d2'), 'Principal Staff Distinguished Platform Reliability Engineering Lead', city)

      await page.goto('/login')
      await page.getByLabel('Email').fill(adminEmail)
      await page.getByLabel('Password').fill(E2E_STAFF_PASSWORD)
      await page.getByRole('button', { name: 'Sign in' }).click()
      await expect(page.getByRole('heading', { level: 1, name: 'Candidates' })).toBeVisible()
      await expect(page.getByRole('table')).toBeVisible()
      await shot('07-search-results')
      await page.getByRole('searchbox', { name: 'Search' }).focus()
      await shot('08-search-focus', false)

      // The City filter, not the search box: e2e has no OpenAI key, so searching answers 503.
      const cityFilter = page.getByRole('textbox', { name: 'City' })
      await cityFilter.fill('zzzznomatchzzzz')
      await expect(page.getByText('No candidates match your search.')).toBeVisible()
      await shot('09-search-empty')

      await page.route('**/api/v1/admin/candidates**', async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 3000))
        await route.continue()
      })
      await cityFilter.fill('design')
      await page.waitForTimeout(700)
      await shot('10-search-loading')
      await page.unroute('**/api/v1/admin/candidates**')
      await cityFilter.fill(city)
      await page.getByRole('link', { name: firstName, exact: true }).click()
      await expect(page.getByRole('heading', { level: 1, name: firstName })).toBeVisible()
      await shot('11-detail')
      await page.getByRole('button', { name: 'Edit', exact: true }).click()
      await expect(page.getByRole('button', { name: 'Save changes' })).toBeVisible()
      await shot('12-edit')
      await page.getByRole('button', { name: 'Cancel' }).click()

      await page.getByRole('button', { name: 'Delete', exact: true }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
      await shot('13-delete-dialog', false)
      await page.getByRole('button', { name: 'Cancel' }).click()

      await page.goto('/admin/candidates/new')
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await shot('14-create')

      await page.goto('/admin/ai-usage')
      await expect(page.getByRole('heading', { level: 1, name: 'AI spending' })).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Lifetime budget' })).toBeVisible()
      await shot('15-ai-spend')
      await page.getByRole('button', { name: 'Edit limit' }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
      await shot('16-edit-limit-dialog', false)

      expect(overflows, `horizontal page overflow at ${vp.name}`).toEqual([])
      const thirdParty = [...hosts].filter((h) => !/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(h))
      expect(thirdParty, 'third-party hosts requested').toEqual([])
    })
  }

  test('system fonts only: no web fonts are loaded', async ({ page }) => {
    await page.goto('/login')
    await page.evaluate(() => document.fonts.ready)
    const webFonts = await page.evaluate(() => [...document.fonts].map((f) => f.family))
    expect(webFonts).toEqual([])
    const heading = await page.getByRole('heading', { name: 'Staff sign in' }).evaluate((el) => getComputedStyle(el).fontFamily)
    expect(heading).not.toMatch(/Schibsted|Plex/)
  })

  test('light theme is the default: white background, near-black text, blue focus ring', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' })
    await page.goto('/login')
    const colors = await page.evaluate(() => ({
      background: getComputedStyle(document.body).backgroundColor,
      text: getComputedStyle(document.body).color,
      scheme: getComputedStyle(document.documentElement).colorScheme,
    }))
    expect(colors.background).toBe('rgb(255, 255, 255)')
    expect(colors.text).toBe('rgb(17, 17, 19)')
    expect(colors.scheme).toBe('light dark')

    await page.keyboard.press('Tab')
    await page.keyboard.press('Tab')
    const ring = await page.evaluate(() => getComputedStyle(document.activeElement as HTMLElement).outlineColor)
    expect(ring).toBe('rgb(37, 99, 235)')
  })

  test('dark theme follows prefers-color-scheme: near-black background, near-white text, lighter blue ring', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.goto('/login')
    const colors = await page.evaluate(() => ({
      background: getComputedStyle(document.body).backgroundColor,
      text: getComputedStyle(document.body).color,
      input: getComputedStyle(document.querySelector('input') as HTMLElement).backgroundColor,
    }))
    expect(colors.background).toBe('rgb(11, 11, 13)')
    expect(colors.text).toBe('rgb(244, 244, 245)')
    expect(colors.input).toBe('rgb(11, 11, 13)')

    await page.keyboard.press('Tab')
    await page.keyboard.press('Tab')
    const ring = await page.evaluate(() => getComputedStyle(document.activeElement as HTMLElement).outlineColor)
    expect(ring).toBe('rgb(96, 165, 250)')
  })

  test('keyboard: skip link works and focus ring is visible; reduced motion disables transitions', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/login')
    await page.getByLabel('Email').fill(adminEmail)
    await page.getByLabel('Password').fill(E2E_STAFF_PASSWORD)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Candidates' })).toBeVisible()

    await page.reload()
    await expect(page.getByRole('heading', { level: 1, name: 'Candidates' })).toBeVisible()
    await page.keyboard.press('Tab')
    const skip = page.getByRole('link', { name: 'Skip to content' })
    await expect(skip).toBeFocused()
    await expect(skip).toBeVisible()
    if (SCREEN_DIR) await page.screenshot({ path: `${SCREEN_DIR}\\desktop-17-skip-link.png` })
    await page.keyboard.press('Enter')
    await expect.poll(() => page.evaluate(() => location.hash)).toBe('#main')
    const mainTop = await page.evaluate(() => document.getElementById('main')?.getBoundingClientRect().top ?? -1)
    expect(mainTop).toBeGreaterThanOrEqual(0)

    await page.keyboard.press('Tab')
    const ring = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement
      const s = getComputedStyle(el)
      return { tag: el.tagName, width: s.outlineWidth, style: s.outlineStyle, color: s.outlineColor }
    })
    expect(ring.style).toBe('solid')
    expect(parseFloat(ring.width)).toBeGreaterThanOrEqual(2)
    expect(ring.color).toBe('rgb(37, 99, 235)')
    if (SCREEN_DIR) await page.screenshot({ path: `${SCREEN_DIR}\\desktop-18-focus-ring.png` })

    await page.emulateMedia({ reducedMotion: 'reduce' })
    const durations = await page.evaluate(() =>
      [...document.querySelectorAll('a, button, tr, input')].map((el) => getComputedStyle(el).transitionDuration),
    )
    for (const d of durations) {
      for (const part of d.split(',')) expect(parseFloat(part)).toBeLessThanOrEqual(0.001)
    }
  })

  test('sidebar active state and phone top bar', async ({ page }) => {
    await page.setViewportSize({ width: 400, height: 860 })
    await page.goto('/login')
    await page.getByLabel('Email').fill(adminEmail)
    await page.getByLabel('Password').fill(E2E_STAFF_PASSWORD)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Candidates' })).toBeVisible()
    const active = page.getByRole('link', { name: 'Candidates', exact: true })
    const border = await active.evaluate((el) => getComputedStyle(el).borderBottomColor)
    expect(border).not.toBe('rgba(0, 0, 0, 0)')
    await expect(page.getByRole('link', { name: 'AI spending' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
  })
})
