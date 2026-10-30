/**
 * Vite config for Playwright runs: same app, but on its own ports so e2e never touches the
 * dev servers (5180/8010) or the dev database. The e2e API (8011) uses the test database.
 */
import { defineConfig, mergeConfig } from 'vite'
import baseConfig from './vite.config.ts'

export const E2E_WEB_PORT = 5181
export const E2E_API_TARGET = 'http://localhost:8011'

export default mergeConfig(
  baseConfig,
  defineConfig({
    server: {
      port: E2E_WEB_PORT,
      strictPort: true,
      proxy: {
        '/api': E2E_API_TARGET,
        '/health': E2E_API_TARGET,
        '/ready': E2E_API_TARGET,
      },
    },
  }),
)
