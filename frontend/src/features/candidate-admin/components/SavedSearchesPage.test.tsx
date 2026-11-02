import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route, stubApi } from '@/test/fakeApi'
import type { SavedSearchSummary } from '../types'
import { SavedSearchesPage } from './SavedSearchesPage'

const HISTORY = '/api/v1/semantic-search/history'

const saved = (overrides: Partial<SavedSearchSummary> = {}): SavedSearchSummary => ({
  id: 's-1',
  query: 'python developer',
  filters: { country: 'IN', min_years: '3' },
  result_count: 12,
  filtered_out_count: 2,
  starred: false,
  created_at: '2026-11-02T10:00:00Z',
  ...overrides,
})

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SavedSearchesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

describe('SavedSearchesPage', () => {
  it('lists starred searches first, each opening its saved copy', async () => {
    stubApi(
      route('GET', HISTORY, {
        body: { items: [saved(), saved({ id: 's-2', query: 'devops lead', filters: {}, starred: true })], next_cursor: null },
      }),
    )
    renderPage()

    const starred = await screen.findByRole('region', { name: 'Starred' })
    expect(within(starred).getByRole('link', { name: 'devops lead' })).toHaveAttribute(
      'href',
      '/admin/candidates?q=devops+lead&search=s-2',
    )
    const recent = screen.getByRole('region', { name: 'Recent' })
    expect(within(recent).getByRole('link', { name: 'python developer' })).toHaveAttribute(
      'href',
      '/admin/candidates?q=python+developer&country=IN&min_years=3&search=s-1',
    )
    expect(recent).toHaveTextContent('Country: IN · Min years: 3')
    expect(recent).toHaveTextContent('12 matches, 2 filtered out')
  })

  it('stars and deletes a search', async () => {
    const fetchMock = stubApi(
      route('GET', HISTORY, { body: { items: [saved()], next_cursor: null } }),
      route('PUT', `${HISTORY}/s-1/star`, { status: 204 }),
      route('DELETE', `${HISTORY}/s-1`, { status: 204 }),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Star “python developer”' }))
    await user.click(screen.getByRole('button', { name: 'Delete “python developer”' }))

    const calls = fetchMock.mock.calls.map(([input, init]) => [init?.method ?? 'GET', new URL(input, 'http://localhost').pathname])
    expect(calls).toContainEqual(['PUT', `${HISTORY}/s-1/star`])
    expect(calls).toContainEqual(['DELETE', `${HISTORY}/s-1`])
  })

  it('says how to start when there are no searches yet', async () => {
    stubApi(route('GET', HISTORY, { body: { items: [], next_cursor: null } }))
    renderPage()

    expect(await screen.findByText(/No searches yet/)).toBeInTheDocument()
  })
})
