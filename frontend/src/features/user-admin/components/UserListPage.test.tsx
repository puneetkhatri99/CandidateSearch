import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route, staffUser, stubApi } from '@/test/fakeApi'
import { userAccount } from '../testing'
import { UserListPage } from './UserListPage'

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <UserListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

const admin = userAccount({ id: 'u-1', email: 'boss@example.com', full_name: 'Boss Admin', role: 'admin' })
const me = route('GET', '/api/v1/auth/me', { body: staffUser({ id: 'u-1', role: 'admin', full_name: 'Boss Admin' }) })
const users = (...items: ReturnType<typeof userAccount>[]) =>
  route('GET', '/api/v1/admin/users', { body: { items, next_cursor: null } })

describe('UserListPage', () => {
  it('lists accounts with role and status stamps and mono dates', async () => {
    stubApi(me, users(admin, userAccount({ must_change_password: true }), userAccount({ id: 'u-3', full_name: 'Sam Off', email: 'sam@example.com', is_active: false, last_login_at: null })))
    renderPage()

    expect(await screen.findByRole('table', { name: 'Staff accounts' })).toBeInTheDocument()
    expect(screen.getByText('Rita Recruiter')).toBeInTheDocument()
    expect(screen.getByText('rita@example.com')).toHaveClass('num')
    expect(screen.getByText('Must change password')).toBeInTheDocument()
    expect(screen.getByText('Inactive')).toBeInTheDocument()
    expect(screen.getByText('Never')).toHaveClass('num')
    expect(screen.getByText('Showing 3')).toBeInTheDocument()
  })

  it('offers no actions on the admin’s own row', async () => {
    stubApi(me, users(admin, userAccount()))
    renderPage()

    await screen.findByText('Rita Recruiter')

    expect(screen.queryByRole('button', { name: /Boss Admin/ })).not.toBeInTheDocument()
    expect(screen.getByText('This is you')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reset password for Rita Recruiter' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Deactivate Rita Recruiter' })).toBeInTheDocument()
  })

  it('offers Reactivate for an inactive account', async () => {
    stubApi(me, users(admin, userAccount({ is_active: false })))
    renderPage()

    expect(await screen.findByRole('button', { name: 'Reactivate Rita Recruiter' })).toBeInTheDocument()
  })

  it('deactivates after a confirmation that says they are signed out', async () => {
    let active = true
    const fetchMock = stubApi(
      me,
      route('PATCH', '/api/v1/admin/users/u-2', (_, init) => {
        active = JSON.parse(init.body as string).is_active
        return { body: userAccount({ is_active: active }) }
      }),
      route('GET', '/api/v1/admin/users', () => ({ body: { items: [admin, userAccount({ is_active: active })], next_cursor: null } })),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Deactivate Rita Recruiter' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Deactivate Rita Recruiter?')).toBeInTheDocument()
    expect(within(dialog).getByText(/signed out immediately/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Deactivate' }))

    expect(await screen.findByRole('button', { name: 'Reactivate Rita Recruiter' })).toBeInTheDocument()
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(JSON.parse(patch?.[1]?.body as string)).toEqual({ is_active: false })
  })

  it('cancels a dialog with Escape without calling the API', async () => {
    const fetchMock = stubApi(me, users(admin, userAccount()))
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Deactivate Rita Recruiter' }))
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))

    expect(screen.queryByText('Deactivate Rita Recruiter?')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(false)
  })

  it('resets a password with a generated temporary password', async () => {
    const fetchMock = stubApi(
      me,
      users(admin, userAccount()),
      route('POST', '/api/v1/admin/users/u-2/reset-password', { body: userAccount({ must_change_password: true }) }),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Reset password for Rita Recruiter' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/signed out everywhere/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Generate' }))
    const generated = (within(dialog).getByLabelText(/Temporary password/) as HTMLInputElement).value
    expect(generated).toHaveLength(16)
    await user.click(within(dialog).getByRole('button', { name: 'Reset password' }))

    await screen.findByText('Rita Recruiter')
    const post = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith('/reset-password') && init?.method === 'POST')
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({ temporary_password: generated })
  })

  it('loads more accounts with the cursor', async () => {
    stubApi(
      me,
      route('GET', '/api/v1/admin/users', (url) =>
        url.searchParams.get('cursor') === 'abc'
          ? { body: { items: [userAccount({ id: 'u-9', full_name: 'Zed Late', email: 'zed@example.com' })], next_cursor: null } }
          : { body: { items: [admin], next_cursor: 'abc' } },
      ),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Load more' }))

    expect(await screen.findByText('Zed Late')).toBeInTheDocument()
  })

  it('shows an error when the list fails', async () => {
    stubApi(me, route('GET', '/api/v1/admin/users', { status: 403, body: { error: { code: 'forbidden', message: 'No access.', details: {} } } }))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('No access.')
  })
})
