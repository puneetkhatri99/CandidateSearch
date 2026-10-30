import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route, stubApi } from '@/test/fakeApi'
import { candidateDetail } from '../testing'
import { CandidateDetailPage } from './CandidateDetailPage'

const me = (role: 'admin' | 'recruiter') =>
  route('GET', '/api/v1/auth/me', { body: { id: 'u-1', email: 'staff@example.com', full_name: 'Staff', role } })
const detail = route('GET', '/api/v1/admin/candidates/c-1', { body: candidateDetail() })

function renderPage(initialUrl = '/admin/candidates/c-1') {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[initialUrl]}>
        <Routes>
          <Route path="/admin/candidates/:id" element={<CandidateDetailPage />} />
          <Route path="/admin/candidates" element={<p>Search page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

describe('CandidateDetailPage', () => {
  it('shows the full profile', async () => {
    stubApi(me('admin'), detail)
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Asha Verma' })).toBeInTheDocument()
    expect(screen.getByText('asha@example.com')).toBeInTheDocument()
    expect(screen.getByText('Engineer · Acme')).toBeInTheDocument()
    expect(screen.getByText('IIT Delhi')).toBeInTheDocument()
  })

  it('opens straight into the edit form from the table Edit link', async () => {
    stubApi(me('recruiter'), detail)
    renderPage('/admin/candidates/c-1?edit=1')

    expect(await screen.findByRole('button', { name: /save/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  })

  it('hides Delete from recruiters', async () => {
    stubApi(me('recruiter'), detail)
    renderPage()

    await screen.findByRole('button', { name: 'Edit' })

    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })

  it('admin deletes after confirming and returns to search', async () => {
    const fetchMock = stubApi(me('admin'), detail, route('DELETE', '/api/v1/admin/candidates/c-1', { status: 204 }))
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    expect(screen.getByRole('heading', { name: 'Delete Asha Verma?' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Delete permanently' }))

    expect(await screen.findByText('Search page')).toBeInTheDocument()
    const deleteCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'DELETE')
    expect(deleteCall?.[1]?.headers).toMatchObject({ 'X-Requested-With': 'fetch' })
  })

  it('saves edits with the loaded version and shows the updated profile', async () => {
    const fetchMock = stubApi(
      me('admin'),
      detail,
      route('PUT', '/api/v1/admin/candidates/c-1', (_, init) => {
        const body = JSON.parse(String(init.body)) as { headline: string }
        return { body: candidateDetail({ version: 4, headline: body.headline }) }
      }),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Edit' }))
    const headline = screen.getByLabelText(/Headline/)
    await user.clear(headline)
    await user.type(headline, 'Staff Engineer')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(screen.getByText('Staff Engineer')).toBeInTheDocument()
    const putCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(JSON.parse(String(putCall?.[1]?.body))).toMatchObject({ version: 3, headline: 'Staff Engineer' })
  })

  it('explains a version conflict and offers to reload', async () => {
    stubApi(
      me('admin'),
      detail,
      route('PUT', '/api/v1/admin/candidates/c-1', {
        status: 409,
        body: { error: { code: 'version_conflict', message: 'This profile was changed by someone else.', details: {} } },
      }),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Edit' }))
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByText(/changed by someone else/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Discard my changes and reload' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument())
  })

  it('shows not-found for a deleted candidate', async () => {
    stubApi(me('admin'))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('does not exist or was deleted')
  })
})
