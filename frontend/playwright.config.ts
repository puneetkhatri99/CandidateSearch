/**
 * End-to-end tests (chromium only).
 *
 * Playwright starts its own stack so it never touches the dev servers or the dev database:
 *   - API on 8011 (ENVIRONMENT=test, the `<dev db>_test` database, migrated first)
 *   - Vite on 5181, proxying /api to 8011
 * Candidates created by e2e use `e2e-...@example.com` and are deleted in global teardown.
 */
import { defineConfig, devices } from '@playwright/test'
import { e2eEnvironment } from './e2e/support/backend.ts'

const BACKEND_DIR = '../backend'
const bin = (name: string) => (process.platform === 'win32' ? `.venv\\Scripts\\${name}.exe` : `.venv/bin/${name}`)

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  globalTeardown: './e2e/global-teardown.ts',
  use: {
    baseURL: 'http://localhost:5181',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `${bin('alembic')} upgrade head && ${bin('uvicorn')} app.main:app --port 8011`,
      cwd: BACKEND_DIR,
      env: e2eEnvironment(),
      url: 'http://localhost:8011/health',
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'npx vite --config vite.e2e.config.ts',
      url: 'http://localhost:5181',
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
