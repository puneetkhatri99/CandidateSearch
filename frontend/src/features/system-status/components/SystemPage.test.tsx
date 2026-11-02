import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route, stubApi } from '@/test/fakeApi'
import type { SystemDetails } from '../types'
import { SystemPage } from './SystemPage'

const details: SystemDetails = {
  models: {
    embedding_model: 'text-embedding-3-small',
    ranking_model: 'gpt-5.4-mini',
    ranking_prompt_version: 'rank_v4',
    understanding_prompt_version: 'understand_v1',
  },
  candidates: { total: 1001, current: 1001, failed: 0 },
  jobs: { total: 4, current: 3, failed: 1 },
  budget: { spent_usd: '0.71', limit_usd: '5.00', limit_reached: false },
}

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SystemPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const row = (label: string) => screen.getByText(label, { selector: 'dt' }).nextElementSibling

describe('SystemPage', () => {
  it('shows the live status, embedding coverage, budget and models', async () => {
    stubApi(
      route('GET', '/ready', { body: { status: 'ok', checks: { database: true, pgvector: true } } }),
      route('GET', '/api/v1/admin/system', { body: details }),
    )
    renderPage()

    expect(await screen.findByText('1,001 of 1,001 candidates up to date')).toBeInTheDocument()
    expect(row('Jobs')).toHaveTextContent('3 of 4 jobs up to date, 1 failed')
    expect(row('AI budget')).toHaveTextContent('$0.71 of $5.00 used')
    expect(row('Ranking')).toHaveTextContent('gpt-5.4-mini, prompt rank_v4')
    expect(row('API')).toHaveTextContent('Online')
    expect(row('Database')).toHaveTextContent('Online')
    expect(row('Last checked')).not.toHaveTextContent('Checking')
  })

  it('names the dependency that is down, from the 503 body', async () => {
    stubApi(
      route('GET', '/ready', { status: 503, body: { status: 'unavailable', checks: { database: true, pgvector: false } } }),
      route('GET', '/api/v1/admin/system', { body: details }),
    )
    renderPage()

    expect(await screen.findByText('pgvector unavailable')).toBeInTheDocument()
    expect(row('Database')).toHaveTextContent('Online')
    expect(row('API')).toHaveTextContent('Up, but a dependency below is down')
  })

  it('keeps the status when the details cannot be loaded', async () => {
    stubApi(
      route('GET', '/ready', { body: { status: 'ok', checks: { database: true, pgvector: true } } }),
      route('GET', '/api/v1/admin/system', { status: 500, body: { error: { code: 'internal_error', message: 'x', details: {} } } }),
    )
    renderPage()

    expect(await screen.findByText(/Could not load the search details/)).toBeInTheDocument()
    expect(row('API')).toHaveTextContent('Online')
  })
})
