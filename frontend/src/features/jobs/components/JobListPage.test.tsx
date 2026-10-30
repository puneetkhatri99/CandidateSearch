import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route, stubApi } from '@/test/fakeApi'
import { jobSummary } from '../testing'
import { JobListPage } from './JobListPage'

function renderPage(initialUrl = '/jobs') {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[initialUrl]}>
        <JobListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

const listCalls = (fetchMock: ReturnType<typeof stubApi>) =>
  fetchMock.mock.calls.map(([input]) => new URL(input, 'http://localhost')).filter((url) => url.pathname === '/api/v1/jobs')

describe('JobListPage', () => {
  it('lists jobs with a link to each and mono figures', async () => {
    stubApi(route('GET', '/api/v1/jobs', { body: { items: [jobSummary()], next_cursor: null } }))
    renderPage()

    const link = await screen.findByRole('link', { name: 'Senior Backend Engineer' })

    expect(link).toHaveAttribute('href', '/jobs/j-1')
    expect(screen.getByRole('table', { name: 'Job roles' })).toBeInTheDocument()
    expect(screen.getByText('03.0–06.0')).toHaveClass('num')
    expect(screen.getByText('Showing 1 job')).toBeInTheDocument()
    expect(screen.getByText('Berlin, Germany')).toBeInTheDocument()
    expect(screen.getByText('Rita Recruiter')).toBeInTheDocument()
  })

  it('shows the first five must-haves and a count for the rest', async () => {
    const skills = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
    stubApi(route('GET', '/api/v1/jobs', { body: { items: [jobSummary({ must_have_skills: skills })], next_cursor: null } }))
    renderPage()

    await screen.findByText('e')

    expect(screen.queryByText('f')).not.toBeInTheDocument()
    expect(screen.getByText('+2')).toBeInTheDocument()
  })

  it('keeps the status filter in the URL and sends it to the API', async () => {
    const fetchMock = stubApi(route('GET', '/api/v1/jobs', { body: { items: [], next_cursor: null } }))
    const user = renderPage('/jobs?status=open')
    await screen.findByText('No open jobs.')

    expect(listCalls(fetchMock)[0]?.searchParams.get('status')).toBe('open')
    expect(screen.getByLabelText('Status')).toHaveValue('open')

    await user.selectOptions(screen.getByLabelText('Status'), 'closed')

    await screen.findByText('No closed jobs.')
    expect(listCalls(fetchMock).at(-1)?.searchParams.get('status')).toBe('closed')
  })

  it('loads the next page with the cursor', async () => {
    const fetchMock = stubApi(
      route('GET', '/api/v1/jobs', (url) =>
        url.searchParams.get('cursor') === 'abc'
          ? { body: { items: [jobSummary({ id: 'j-2', title: 'Data Engineer' })], next_cursor: null } }
          : { body: { items: [jobSummary()], next_cursor: 'abc' } },
      ),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Load more' }))

    expect(await screen.findByRole('link', { name: 'Data Engineer' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Senior Backend Engineer' })).toBeInTheDocument()
    expect(listCalls(fetchMock).at(-1)?.searchParams.get('cursor')).toBe('abc')
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  it('offers to add the first job when there are none', async () => {
    stubApi(route('GET', '/api/v1/jobs', { body: { items: [], next_cursor: null } }))
    renderPage()

    expect(await screen.findByText('No jobs yet.')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Add job' }).length).toBeGreaterThan(0)
  })

  it('shows an error when the list fails', async () => {
    stubApi(
      route('GET', '/api/v1/jobs', {
        status: 500,
        body: { error: { code: 'internal_error', message: 'An unexpected error occurred.', details: {} } },
      }),
    )
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('An unexpected error occurred.')
  })
})
