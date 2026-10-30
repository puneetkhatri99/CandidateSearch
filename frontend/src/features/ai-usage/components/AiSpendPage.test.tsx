import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route, stubApi } from '@/test/fakeApi'
import { budgetSummary, usageEvent } from '../testing'
import { AiSpendPage } from './AiSpendPage'

function renderPage(initialUrl = '/admin/ai-usage') {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[initialUrl]}>
        <AiSpendPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

const me = (role: 'admin' | 'recruiter') =>
  route('GET', '/api/v1/auth/me', { body: { id: 'u-1', email: 'staff@example.com', full_name: 'Staff', role } })
const summaryRoute = (overrides = {}) => route('GET', '/api/v1/ai-usage/summary', { body: budgetSummary(overrides) })
const eventsRoute = (items = [usageEvent()], next_cursor: string | null = null) =>
  route('GET', '/api/v1/ai-usage/events', { body: { items, next_cursor } })

const eventCalls = (fetchMock: ReturnType<typeof stubApi>) =>
  fetchMock.mock.calls.map(([input]) => new URL(input, 'http://localhost')).filter((u) => u.pathname === '/api/v1/ai-usage/events')

describe('AiSpendPage', () => {
  it('shows the budget, totals by model and operation, and the request log', async () => {
    stubApi(me('recruiter'), summaryRoute(), eventsRoute())
    renderPage()

    expect(await screen.findByText(/of \$5\.00/)).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Spending by model' })).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Spending by operation' })).toBeInTheDocument()
    const log = await screen.findByRole('table', { name: 'AI request log, newest first' })
    expect(within(log).getByText('succeeded', { selector: 'span' })).toBeInTheDocument()
    expect(within(log).getByText('<$0.0001')).toBeInTheDocument()
  })

  it('hides Edit limit from recruiters', async () => {
    stubApi(me('recruiter'), summaryRoute(), eventsRoute())
    renderPage()

    await screen.findByText(/of \$5\.00/)

    expect(screen.queryByRole('button', { name: 'Edit limit' })).not.toBeInTheDocument()
  })

  it('lets an admin change the limit and shows the new value', async () => {
    let limit = '5.00'
    const fetchMock = stubApi(
      me('admin'),
      route('PUT', '/api/v1/ai-usage/budget', (_url, init) => {
        limit = (JSON.parse(String(init.body)) as { limit_usd: string }).limit_usd
        return { body: budgetSummary({ limit_usd: limit }) }
      }),
      route('GET', '/api/v1/ai-usage/summary', () => ({ body: budgetSummary({ limit_usd: limit }) })),
      eventsRoute(),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Edit limit' }))
    const input = screen.getByLabelText('Limit (USD)')
    await user.clear(input)
    await user.type(input, '12.5')
    await user.click(screen.getByRole('button', { name: 'Save limit' }))

    expect(await screen.findByText(/of \$12\.50/)).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(true)
  })

  it('rejects an invalid limit before calling the API', async () => {
    const fetchMock = stubApi(me('admin'), summaryRoute(), eventsRoute())
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Edit limit' }))
    const input = screen.getByLabelText('Limit (USD)')
    await user.clear(input)
    await user.type(input, '20000')
    await user.click(screen.getByRole('button', { name: 'Save limit' }))

    expect(await screen.findByText(/cannot be more than/)).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false)
  })

  it('puts the filters into the request URL', async () => {
    const fetchMock = stubApi(me('recruiter'), summaryRoute(), eventsRoute())
    const user = renderPage('/admin/ai-usage?operation=candidate_embedding')

    await screen.findByRole('table', { name: 'AI request log, newest first' })
    expect(eventCalls(fetchMock)[0]?.searchParams.get('operation')).toBe('candidate_embedding')

    await user.selectOptions(screen.getByLabelText('Status'), 'blocked')

    await screen.findByRole('table', { name: 'AI request log, newest first' })
    const last = eventCalls(fetchMock).at(-1)?.searchParams
    expect(last?.get('status')).toBe('blocked')
    expect(last?.get('operation')).toBe('candidate_embedding')
  })

  it('loads the next page with the cursor', async () => {
    const fetchMock = stubApi(
      me('recruiter'),
      summaryRoute(),
      route('GET', '/api/v1/ai-usage/events', (url) =>
        url.searchParams.get('cursor') === 'abc'
          ? { body: { items: [usageEvent({ id: 'e-2', status: 'failed', item_count: 77 })], next_cursor: null } }
          : { body: { items: [usageEvent()], next_cursor: 'abc' } },
      ),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Load more' }))

    expect(await screen.findByText('failed', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByText('succeeded', { selector: 'span' })).toBeInTheDocument()
    expect(eventCalls(fetchMock).at(-1)?.searchParams.get('cursor')).toBe('abc')
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  it('highlights blocked rows', async () => {
    stubApi(me('recruiter'), summaryRoute(), eventsRoute([usageEvent({ status: 'blocked', cost_usd: '0' })]))
    renderPage()

    const badge = await screen.findByText('blocked', { selector: 'span' })

    expect(badge.closest('tr')).toHaveClass('bg-danger-soft')
  })

  it('shows loading skeletons, then an empty state', async () => {
    stubApi(me('recruiter'), summaryRoute(), eventsRoute([]))
    renderPage()

    expect(screen.getAllByRole('status').length).toBeGreaterThan(0)
    expect(await screen.findByText('No AI requests yet.')).toBeInTheDocument()
  })

  it('shows an error when the summary fails', async () => {
    stubApi(
      me('recruiter'),
      route('GET', '/api/v1/ai-usage/summary', {
        status: 500,
        body: { error: { code: 'internal_error', message: 'An unexpected error occurred.', details: {} } },
      }),
      eventsRoute(),
    )
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('An unexpected error occurred.')
  })
})