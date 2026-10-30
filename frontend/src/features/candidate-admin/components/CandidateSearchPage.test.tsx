import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { route, sseBody, stubApi } from '@/test/fakeApi'
import { candidateSummary } from '../testing'
import { CandidateSearchPage } from './CandidateSearchPage'

function renderPage(initialUrl = '/admin/candidates') {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[initialUrl]}>
        <CandidateSearchPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

const searchCalls = (fetchMock: ReturnType<typeof stubApi>) =>
  fetchMock.mock.calls.map(([input]) => new URL(input, 'http://localhost')).filter((u) => u.pathname === '/api/v1/admin/candidates')

describe('CandidateSearchPage', () => {
  it('lists candidates with a link to each profile', async () => {
    stubApi(route('GET', '/api/v1/admin/candidates', { body: { items: [candidateSummary()], next_cursor: null } }))
    renderPage()

    const link = await screen.findByRole('link', { name: 'Asha Verma' })

    expect(link).toHaveAttribute('href', '/admin/candidates/c-1')
    expect(screen.getByRole('table', { name: 'Candidates matching your search' })).toBeInTheDocument()
    expect(screen.getByText('Showing 1 candidate')).toBeInTheDocument()
    // One search box: no mode to choose.
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  })

  it('applies the filters from the URL when browsing without search text', async () => {
    const fetchMock = stubApi(route('GET', '/api/v1/admin/candidates', { body: { items: [], next_cursor: null } }))
    renderPage('/admin/candidates?country=IN&city=Pune&skill=python,+fastapi&min_years=3&source=manual')

    await screen.findByText('No candidates match your search.')

    const params = searchCalls(fetchMock)[0]?.searchParams
    expect(params?.get('country')).toBe('IN')
    expect(params?.get('city')).toBe('Pune')
    expect(params?.get('skill')).toBe('python, fastapi')
    expect(params?.get('min_years')).toBe('3')
    expect(params?.get('source')).toBe('manual')
    expect(params?.has('q')).toBe(false)
  })

  it('loads the next page with the cursor', async () => {
    const fetchMock = stubApi(
      route('GET', '/api/v1/admin/candidates', (url) =>
        url.searchParams.get('cursor') === 'abc'
          ? { body: { items: [candidateSummary({ id: 'c-2', full_name: 'Ravi Kumar' })], next_cursor: null } }
          : { body: { items: [candidateSummary()], next_cursor: 'abc' } },
      ),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Load more' }))

    expect(await screen.findByRole('link', { name: 'Ravi Kumar' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Asha Verma' })).toBeInTheDocument()
    expect(searchCalls(fetchMock).at(-1)?.searchParams.get('cursor')).toBe('abc')
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  const me = (role: 'admin' | 'recruiter') =>
    route('GET', '/api/v1/auth/me', { body: { id: 'u-1', email: 'staff@example.com', full_name: 'Staff', role } })

  it('shows email in its own column and an Edit action that opens the form', async () => {
    stubApi(me('recruiter'), route('GET', '/api/v1/admin/candidates', { body: { items: [candidateSummary()], next_cursor: null } }))
    renderPage()

    const edit = await screen.findByRole('link', { name: 'Edit Asha Verma' })

    expect(edit).toHaveAttribute('href', '/admin/candidates/c-1?edit=1')
    expect(screen.getByRole('columnheader', { name: 'Email' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: candidateSummary().email })).toBeInTheDocument()
  })

  it('hides the row Delete action from recruiters', async () => {
    stubApi(me('recruiter'), route('GET', '/api/v1/admin/candidates', { body: { items: [candidateSummary()], next_cursor: null } }))
    renderPage()

    await screen.findByRole('link', { name: 'Edit Asha Verma' })

    expect(screen.queryByRole('button', { name: 'Delete Asha Verma' })).not.toBeInTheDocument()
  })

  it('lets an admin delete a row after confirming', async () => {
    let deleted = false
    const fetchMock = stubApi(
      me('admin'),
      route('DELETE', '/api/v1/admin/candidates/c-1', () => {
        deleted = true
        return { status: 204 }
      }),
      route('GET', '/api/v1/admin/candidates', () => ({
        body: { items: deleted ? [] : [candidateSummary()], next_cursor: null },
      })),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Delete Asha Verma' }))
    await user.click(screen.getByRole('button', { name: 'Delete permanently' }))

    expect(await screen.findByText('No candidates match your search.')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true)
  })

  it('shows a loading skeleton while the first page loads', async () => {
    stubApi(route('GET', '/api/v1/admin/candidates', { body: { items: [], next_cursor: null } }))
    renderPage()

    expect(screen.getByRole('status')).toHaveTextContent('Loading candidates…')
    await screen.findByText('No candidates match your search.')
  })

  const meaningUrl = '/api/v1/semantic-search/candidates/stream'
  const meaningCalls = (fetchMock: ReturnType<typeof stubApi>) =>
    fetchMock.mock.calls.map(([input]) => new URL(input, 'http://localhost')).filter((u) => u.pathname === meaningUrl)

  /** A streamed search: one finished step, then the result. Spread into a route response. */
  const result = (overrides: Record<string, unknown> = {}) => ({
    stream: sseBody(
      ['stage', { stage: 'embedding', state: 'done', detail: 'Search embedded', elapsed_ms: 120 }],
      [
        'result',
        {
          ranked_by: 'ai',
          embedding_model: 'text-embedding-3-small',
          ranking_model: 'gpt-5.4-mini',
          prompt_version: 'rank_v3',
          items: [],
          filtered_out: [],
          ...overrides,
        },
      ],
    ),
  })

  it('searches from a link and shows the fit with its reasons', async () => {
    const fetchMock = stubApi(
      route('GET', meaningUrl, {
        ...result({
          items: [
            {
              candidate: candidateSummary(),
              fit: 'partial',
              criteria: [
                { name: 'skills', status: 'met', note: 'Python, FastAPI' },
                { name: 'location', status: 'missed', note: 'Lives in Pune' },
              ],
              failed_filters: [],
            },
          ],
        }),
      }),
    )
    renderPage('/admin/candidates?q=payments+backend+engineer')

    expect(await screen.findByRole('link', { name: 'Asha Verma' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Match' })).toBeInTheDocument()
    const cell = screen.getByRole('cell', { name: /^Partial/ })
    expect(cell).toHaveTextContent('met: Skills: Python, FastAPI')
    expect(cell).toHaveTextContent('not met: Location: Lives in Pune')
    expect(screen.getByText(/Ranked by AI/)).toBeInTheDocument()
    expect(screen.getByText('Top 1 candidate, best match first')).toBeInTheDocument()
    // No filters, so no split into sections.
    expect(screen.queryByRole('heading', { name: 'Filtered out' })).not.toBeInTheDocument()
    expect(meaningCalls(fetchMock)[0]?.searchParams.get('q')).toBe('payments backend engineer')
    // The plain list doesn't run alongside it.
    expect(searchCalls(fetchMock)).toHaveLength(0)
  })

  it('shows perfect matches and filtered-out matches apart, each in ranked order', async () => {
    const fetchMock = stubApi(
      route('GET', meaningUrl, {
        ...result({
          items: [{ candidate: candidateSummary(), fit: 'partial', criteria: [], failed_filters: [] }],
          filtered_out: [
            {
              candidate: candidateSummary({ id: 'c-2', full_name: 'Ravi Kumar' }),
              fit: 'strong',
              criteria: [],
              failed_filters: ['city', 'min_years'],
            },
          ],
        }),
      }),
    )
    renderPage('/admin/candidates?q=fastapi+developer&city=Pune&min_years=5')

    const perfect = await screen.findByRole('table', { name: 'Candidates matching every filter' })
    const removed = screen.getByRole('table', { name: 'Search matches removed by a filter' })
    expect(within(perfect).getByRole('link', { name: 'Asha Verma' })).toBeInTheDocument()
    expect(within(removed).getByRole('link', { name: 'Ravi Kumar' })).toBeInTheDocument()
    expect(within(removed).getByText('Fails filter: City, Min years')).toBeInTheDocument()
    expect(screen.getByText('1 of the top 2 candidates match every filter')).toBeInTheDocument()
    const params = meaningCalls(fetchMock)[0]?.searchParams
    expect([params?.get('city'), params?.get('min_years')]).toEqual(['Pune', '5'])
  })

  it('says so when no top result passes every filter, and still lists the others', async () => {
    stubApi(
      route('GET', meaningUrl, {
        ...result({
          filtered_out: [{ candidate: candidateSummary(), fit: null, criteria: [], failed_filters: ['country'] }],
        }),
      }),
    )
    renderPage('/admin/candidates?q=fastapi+developer&country=DE')

    expect(await screen.findByText(/No top result matches every filter/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Asha Verma' })).toBeInTheDocument()
    expect(screen.getByText('Fails filter: Country')).toBeInTheDocument()
  })

  it('searches only when Search is pressed, not while typing', async () => {
    const fetchMock = stubApi(
      route('GET', meaningUrl, { ...result() }),
      route('GET', '/api/v1/admin/candidates', { body: { items: [], next_cursor: null } }),
    )
    const user = renderPage()
    await screen.findByText('No candidates match your search.')

    await user.type(screen.getByRole('searchbox', { name: 'Search' }), 'fastapi developer')
    await new Promise((resolve) => setTimeout(resolve, 400)) // longer than the filter debounce
    expect(meaningCalls(fetchMock)).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(meaningCalls(fetchMock)).toHaveLength(1))
    expect(meaningCalls(fetchMock)[0]?.searchParams.get('q')).toBe('fastapi developer')
  })

  it('applies changed filters to a search only when Search is pressed again', async () => {
    const fetchMock = stubApi(route('GET', meaningUrl, { ...result() }))
    const user = renderPage('/admin/candidates?q=fastapi+developer&city=Pune')
    await waitFor(() => expect(meaningCalls(fetchMock)).toHaveLength(1))

    const city = screen.getByRole('textbox', { name: 'City' })
    await user.clear(city)
    await user.type(city, 'Delhi')
    await new Promise((resolve) => setTimeout(resolve, 400)) // longer than the filter debounce
    expect(meaningCalls(fetchMock)).toHaveLength(1) // each search is paid
    expect(screen.getByText('Press Search to apply the changed filters.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() => expect(meaningCalls(fetchMock)).toHaveLength(2))
    expect(meaningCalls(fetchMock)[1]?.searchParams.get('city')).toBe('Delhi')
    expect(screen.queryByText('Press Search to apply the changed filters.')).not.toBeInTheDocument()
  })

  it('goes back to browsing when the search box is emptied', async () => {
    const fetchMock = stubApi(
      route('GET', meaningUrl, { ...result() }),
      route('GET', '/api/v1/admin/candidates', { body: { items: [candidateSummary()], next_cursor: null } }),
    )
    const user = renderPage('/admin/candidates?q=python')
    await screen.findByText('No candidates match your search.')

    await user.clear(screen.getByRole('searchbox', { name: 'Search' }))

    expect(await screen.findByRole('link', { name: 'Asha Verma' })).toBeInTheDocument()
    expect(meaningCalls(fetchMock)).toHaveLength(1)
  })

  it('shows an error sent inside the stream', async () => {
    stubApi(
      route('GET', meaningUrl, {
        stream: sseBody(
          ['stage', { stage: 'embedding', state: 'started', detail: 'Turning your search into an embedding', elapsed_ms: null }],
          ['error', { status: 402, code: 'budget_exceeded', message: 'The AI spending limit has been reached.' }],
        ),
      }),
    )
    renderPage('/admin/candidates?q=python')

    expect(await screen.findByRole('alert')).toHaveTextContent('The AI spending limit has been reached.')
  })

  it('shows an error returned before the stream starts', async () => {
    stubApi(
      route('GET', meaningUrl, {
        status: 422,
        body: { error: { code: 'query_not_searchable_by_meaning', message: "Emails can't be searched.", details: {} } },
      }),
    )
    renderPage('/admin/candidates?q=me%40x.io')

    expect(await screen.findByRole('alert')).toHaveTextContent("Emails can't be searched.")
  })

  it('shows each step as it streams in', async () => {
    let finish: (value: void) => void = () => {}
    const finished = new Promise<void>((resolve) => (finish = resolve))
    const encoder = new TextEncoder()
    const event = (name: string, data: unknown) => encoder.encode(sseBody([name, data]))
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        const body = new ReadableStream<Uint8Array>({
          async start(controller) {
            controller.enqueue(event('stage', { stage: 'embedding', state: 'done', detail: 'Search embedded', elapsed_ms: 140 }))
            controller.enqueue(
              event('stage', { stage: 'retrieval', state: 'started', detail: 'Searching profiles', elapsed_ms: null }),
            )
            await finished
            controller.enqueue(event('result', JSON.parse(result().stream.split('data: ').at(-1) ?? '{}')))
            controller.close()
          },
        })
        return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
      }),
    )
    renderPage('/admin/candidates?q=python')

    const steps = await screen.findByRole('list', { name: 'Search progress' })
    await waitFor(() => expect(within(steps).getByText('Search embedded')).toBeInTheDocument())
    expect(within(steps).getByText('140 ms')).toBeInTheDocument()
    expect(within(steps).getByText('Retrieval').closest('li')).toHaveAttribute('data-status', 'active')
    expect(within(steps).getByText('AI ranking').closest('li')).toHaveAttribute('data-status', 'waiting')

    finish()

    await waitFor(() => expect(screen.queryByRole('list', { name: 'Search progress' })).not.toBeInTheDocument())
    expect(screen.getByText('No candidates match your search.')).toBeInTheDocument()
  })

  it('shows an error when the search fails', async () => {
    stubApi(
      route('GET', '/api/v1/admin/candidates', {
        status: 500,
        body: { error: { code: 'internal_error', message: 'An unexpected error occurred.', details: {} } },
      }),
    )
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('An unexpected error occurred.')
  })
})
