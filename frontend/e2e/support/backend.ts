import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

export const BACKEND_DIR = fileURLToPath(new URL('../../../backend/', import.meta.url))
const PYTHON = process.platform === 'win32' ? `${BACKEND_DIR}.venv\\Scripts\\python.exe` : `${BACKEND_DIR}.venv/bin/python`

/** Same rule as backend/conftest.py: TEST_DATABASE_URL wins, else `<dev db name>_test`. */
export function testDatabaseUrl(): string {
  if (process.env.TEST_DATABASE_URL) return process.env.TEST_DATABASE_URL
  const env = readFileSync(`${BACKEND_DIR}.env`, 'utf8')
  const devUrl = /^DATABASE_URL\s*=\s*"?([^"\r\n]+)"?/m.exec(env)?.[1]
  if (!devUrl) throw new Error('DATABASE_URL not found in backend/.env; set TEST_DATABASE_URL.')
  const slash = devUrl.lastIndexOf('/')
  return `${devUrl.slice(0, slash)}/${devUrl.slice(slash + 1)}_test`
}

/** Environment for the e2e API process. */
export function e2eEnvironment(): Record<string, string> {
  return {
    ENVIRONMENT: 'test',
    DATABASE_URL: testDatabaseUrl(),
    CORS_ORIGINS: '["http://localhost:5181"]',
    // One e2e run submits a handful of profiles from 127.0.0.1; don't let the limiter flake it.
    CANDIDATE_SUBMIT_LIMIT: '100',
    // No background tasks: embedding in e2e goes through embedQueuedWithMockedOpenAI instead.
    MAINTENANCE_IN_API: 'false',
    // Search by meaning embeds queries inside the request; with the placeholder key it answers
    // 503 instead of calling OpenAI, so no e2e search is ever billed.
    OPENAI_API_KEY: 'sk-CHANGE_ME',
  }
}

const CLEANUP_SCRIPT = `
import asyncio, os, asyncpg
async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    try:
        print(await conn.execute("DELETE FROM candidates WHERE email LIKE 'e2e-%@example.com'"))
        # jobs.created_by is RESTRICT, so jobs must go before their creators (embedding rows cascade).
        await conn.execute("DELETE FROM jobs WHERE created_by IN (SELECT id FROM users WHERE email LIKE 'e2e-%@example.com')")
        # Audit rows hold no PII, but the ones written by e2e staff are test litter.
        await conn.execute("DELETE FROM audit_events WHERE actor_user_id IN (SELECT id FROM users WHERE email LIKE 'e2e-%@example.com')")
        print(await conn.execute("DELETE FROM users WHERE email LIKE 'e2e-%@example.com'"))
    finally:
        await conn.close()
asyncio.run(main())
`

/** Deletes every candidate and staff user created by e2e tests (children go via ON DELETE CASCADE). */
export function deleteE2eCandidates(): string {
  return execFileSync(PYTHON, ['-c', CLEANUP_SCRIPT], {
    cwd: BACKEND_DIR,
    env: { ...process.env, DATABASE_URL: testDatabaseUrl() },
    encoding: 'utf8',
  }).trim()
}

export const uniqueE2eEmail = (label: string) =>
  `e2e-${label}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`

export const E2E_STAFF_PASSWORD = 'e2e-staff-password-123'

/** Creates a staff user in the e2e database through the real CLI (so hashing is the production path). */
export function createE2eStaff(email: string, role: 'admin' | 'recruiter', fullName: string): void {
  execFileSync(PYTHON, ['-m', 'app.cli', 'create-admin', '--email', email, '--name', fullName, '--role', role, '--password-stdin'], {
    cwd: BACKEND_DIR,
    env: { ...process.env, DATABASE_URL: testDatabaseUrl(), ENVIRONMENT: 'test' },
    input: `${E2E_STAFF_PASSWORD}\n`,
    encoding: 'utf8',
  })
}

const EMBED_SCRIPT = `
import asyncio
import httpx2
from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker, register_all_models
from app.core.embeddings import build_embedding_provider
from app.features.embeddings import embed_all_stale
from tests.openai_mock import OpenAIEmbeddingsMock

async def main():
    mock = OpenAIEmbeddingsMock()
    settings = get_settings().model_copy(update={"embedding_max_retries": 0})
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(mock.handler))
    provider = build_embedding_provider(settings, http_client=client)
    try:
        async with get_sessionmaker()() as session:
            await embed_all_stale(session, provider)
    finally:
        await provider.aclose()
        await get_engine().dispose()

register_all_models()
asyncio.run(main())
`

/**
 * Runs one pass of the stale scan (jobs first) in the e2e database, with OpenAI's HTTP layer
 * mocked inside the child process (no network, no real key).
 */
export function embedQueuedWithMockedOpenAI(): void {
  execFileSync(PYTHON, ['-c', EMBED_SCRIPT], {
    cwd: BACKEND_DIR,
    env: { ...process.env, DATABASE_URL: testDatabaseUrl(), ENVIRONMENT: 'test', OPENAI_API_KEY: 'sk-e2e-not-a-real-key' },
    encoding: 'utf8',
  })
}

const COUNT_SCRIPT = `
import asyncio, os, sys, uuid, asyncpg
async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    try:
        print(await conn.fetchval("SELECT count(*) FROM job_embeddings WHERE job_id = $1", uuid.UUID(sys.argv[1])))
    finally:
        await conn.close()
asyncio.run(main())
`

export function jobEmbeddingCount(jobId: string): number {
  const output = execFileSync(PYTHON, ['-c', COUNT_SCRIPT, jobId], {
    cwd: BACKEND_DIR,
    env: { ...process.env, DATABASE_URL: testDatabaseUrl() },
    encoding: 'utf8',
  })
  return Number(output.trim())
}
