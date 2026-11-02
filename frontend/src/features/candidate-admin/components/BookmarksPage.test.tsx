import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route, stubApi } from '@/test/fakeApi'
import { candidateSummary } from '../testing'
import { BookmarksPage } from './BookmarksPage'

const BOOKMARKS = '/api/v1/admin/candidates/bookmarks'
const asha = { candidate: candidateSummary(), added_by_name: 'Priya Shah', added_at: '2026-11-02T10:00:00Z' }

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <BookmarksPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

describe('BookmarksPage', () => {
  it('lists the shared bookmarks with who added them', async () => {
    stubApi(route('GET', BOOKMARKS, { body: { items: [asha] } }))
    renderPage()

    expect(await screen.findByRole('link', { name: asha.candidate.full_name })).toBeInTheDocument()
    expect(screen.getByText('Priya Shah')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: `Bookmark ${asha.candidate.full_name}` })).toHaveAttribute('aria-pressed', 'true')
  })

  it('removes a bookmark when its star is pressed', async () => {
    let items = [asha]
    const fetchMock = stubApi(
      route('GET', BOOKMARKS, () => ({ body: { items } })),
      route('DELETE', `/api/v1/admin/candidates/${asha.candidate.id}/bookmark`, () => {
        items = []
        return { status: 204 }
      }),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: `Bookmark ${asha.candidate.full_name}` }))

    expect(await screen.findByText(/No bookmarks yet/)).toBeInTheDocument()
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'DELETE')
    expect(call?.[1]?.headers).toMatchObject({ 'X-Requested-With': 'fetch' })
  })

  it('says so when there are none', async () => {
    stubApi(route('GET', BOOKMARKS, { body: { items: [] } }))
    renderPage()

    expect(await screen.findByText(/No bookmarks yet/)).toBeInTheDocument()
  })

  it('shows an error when the list fails', async () => {
    stubApi(route('GET', BOOKMARKS, { status: 500, body: { error: { code: 'internal', message: 'Server broke', details: {} } } }))
    renderPage()

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Server broke'))
  })
})
