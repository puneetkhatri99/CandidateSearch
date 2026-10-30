import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route, sseBody, stubApi } from '@/test/fakeApi'
import { jobDetail } from '../testing'
import { JobDetailPage } from './JobDetailPage'

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={['/jobs/j-1']}>
        <Routes>
          <Route path="/jobs/:id" element={<JobDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

const conflict = {
  status: 409,
  body: { error: { code: 'version_conflict', message: 'conflict', details: {} } },
}

describe('JobDetailPage', () => {
  it('shows the job, its status and the embedding state', async () => {
    stubApi(route('GET', '/api/v1/jobs/j-1', { body: jobDetail() }))
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Senior Backend Engineer', level: 1 })).toBeInTheDocument()
    expect(screen.getByText('Open')).toBeInTheDocument()
    expect(screen.getByText('Queued')).toBeInTheDocument()
    expect(screen.getByText('03.0–06.0')).toHaveClass('num')
    expect(screen.getByText('python')).toBeInTheDocument()
    expect(screen.getByText(/You will design and run backend services/)).toHaveClass('whitespace-pre-wrap')
  })

  it.each([
    ['ready', 'Ready'],
    ['failed', 'Failed'],
    ['budget_blocked', 'Waiting for AI budget'],
  ] as const)('labels the %s embedding state', async (embedding_status, label) => {
    stubApi(route('GET', '/api/v1/jobs/j-1', { body: jobDetail({ embedding_status }) }))
    renderPage()

    expect(await screen.findByText(label)).toBeInTheDocument()
  })

  it('shows the yearly pay range', async () => {
    stubApi(route('GET', '/api/v1/jobs/j-1', { body: jobDetail() }))
    renderPage()

    const pay = await screen.findByText(/90,000/)
    expect(pay).toHaveTextContent(/60,000.*–.*90,000/)
  })

  const candidateSummary = (overrides: Record<string, unknown> = {}) => ({
    id: 'c-1',
    full_name: 'Asha Verma',
    email: 'asha@example.com',
    headline: 'Senior Backend Engineer',
    city: 'Berlin',
    country_code: 'DE',
    years_experience: 6.5,
    top_skills: ['python'],
    expected_salary: 80_000,
    salary_currency: 'EUR',
    source: 'manual',
    created_at: '2026-10-27T10:00:00Z',
    ...overrides,
  })
  const matchUrl = '/api/v1/semantic-search/jobs/j-1/candidates/stream'
  const matchResult = {
    ranked_by: 'ai',
    embedding_model: 'text-embedding-3-small',
    ranking_model: 'gpt-5.4-mini',
    prompt_version: 'rank_v2',
    items: [
      {
        candidate: candidateSummary(),
        fit: 'strong',
        criteria: [{ name: 'salary', status: 'met', note: 'Expects 18 LPA, budget 24 LPA' }],
        failed_filters: [],
      },
    ],
    filtered_out: [
      {
        candidate: candidateSummary({ id: 'c-2', full_name: 'Ravi Kumar' }),
        fit: 'strong',
        criteria: [],
        failed_filters: ['city'],
      },
    ],
  }

  it('finds matching candidates only when asked, split by the job requirements', async () => {
    const fetchMock = stubApi(
      route('GET', '/api/v1/jobs/j-1', { body: jobDetail({ embedding_status: 'ready' }) }),
      route('GET', matchUrl, {
        stream: sseBody(
          ['stage', { stage: 'embedding', state: 'done', detail: "Used the job's saved embedding", elapsed_ms: 3 }],
          ['result', matchResult],
        ),
      }),
    )
    const user = renderPage()
    const find = await screen.findByRole('button', { name: 'Find candidates' })
    const matchCalls = () => fetchMock.mock.calls.filter(([input]) => String(input).includes(matchUrl))
    expect(matchCalls()).toHaveLength(0) // a paid AI call: never on page load

    await user.click(find)

    const perfect = await screen.findByRole('table', { name: 'Candidates matching every filter' })
    expect(within(perfect).getByRole('link', { name: 'Asha Verma' })).toBeInTheDocument()
    expect(within(perfect).getByText(/Salary: Expects 18 LPA/)).toBeInTheDocument()
    const removed = screen.getByRole('table', { name: 'Search matches removed by a filter' })
    expect(within(removed).getByText('Fails filter: City')).toBeInTheDocument()
    expect(within(perfect).getByRole('columnheader', { name: 'Expected pay' })).toBeInTheDocument()
    expect(within(perfect).getByText(/80,000/)).toBeInTheDocument()
    expect(matchCalls()).toHaveLength(1)
  })

  it('keeps Find candidates disabled until the job embedding is ready', async () => {
    stubApi(route('GET', '/api/v1/jobs/j-1', { body: jobDetail({ embedding_status: 'budget_blocked' }) }))
    renderPage()

    expect(await screen.findByRole('button', { name: 'Find candidates' })).toBeDisabled()
    expect(screen.getByText('Available once this job’s embedding is ready.')).toBeInTheDocument()
  })

  it('hides Edit and Close when the viewer cannot edit', async () => {
    stubApi(route('GET', '/api/v1/jobs/j-1', { body: jobDetail({ can_edit: false }) }))
    renderPage()

    await screen.findByRole('heading', { name: 'Senior Backend Engineer' })

    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Close job' })).not.toBeInTheDocument()
    expect(screen.getByText('Only the creator or an admin can edit this job.')).toBeInTheDocument()
  })

  it('closes a job after confirming, sending the loaded version', async () => {
    let status = 'open'
    const fetchMock = stubApi(
      route('PATCH', '/api/v1/jobs/j-1', (_, init) => {
        status = JSON.parse(init.body as string).status
        return { body: jobDetail({ status: 'closed', version: 3 }) }
      }),
      route('GET', '/api/v1/jobs/j-1', () => ({ body: jobDetail({ status: status as 'open' }) })),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Close job' }))
    await user.click(screen.getAllByRole('button', { name: 'Close job' }).at(-1) as HTMLElement)

    expect(await screen.findByText('Closed')).toBeInTheDocument()
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(JSON.parse(patch?.[1]?.body as string)).toEqual({ version: 2, status: 'closed' })
    expect(screen.queryByRole('button', { name: 'Close job' })).not.toBeInTheDocument()
  })

  it('shows the conflict message with a reload action when closing hits a newer version', async () => {
    stubApi(route('PATCH', '/api/v1/jobs/j-1', conflict), route('GET', '/api/v1/jobs/j-1', { body: jobDetail() }))
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Close job' }))
    await user.click(screen.getAllByRole('button', { name: 'Close job' }).at(-1) as HTMLElement)

    expect(await screen.findByText(/This job was changed by someone else\. Reload to see the latest version\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
  })

  it('opens the edit form with the stored values', async () => {
    stubApi(route('GET', '/api/v1/jobs/j-1', { body: jobDetail() }))
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Edit' }))

    expect(screen.getByLabelText(/Job title/)).toHaveValue('Senior Backend Engineer')
    expect(screen.getByLabelText(/Minimum years/)).toHaveValue('3')
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeInTheDocument()
  })

  it('shows not-found for an unknown job', async () => {
    stubApi(route('GET', '/api/v1/jobs/j-1', { status: 404, body: { error: { code: 'not_found', message: 'Job not found.', details: {} } } }))
    renderPage()

    expect(await screen.findByText('This job does not exist.')).toBeInTheDocument()
  })
})
