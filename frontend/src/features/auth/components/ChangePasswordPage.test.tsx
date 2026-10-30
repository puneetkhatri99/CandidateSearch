import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route, staffUser, stubApi } from '@/test/fakeApi'
import { ChangePasswordPage } from './ChangePasswordPage'

const NEW_PASSWORD = 'a-brand-new-password'

function renderPage(path = '/account/password') {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/account/password" element={<ChangePasswordPage />} />
          <Route path="/admin/candidates" element={<p>candidates page</p>} />
          <Route path="/jobs" element={<p>jobs page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

async function fill(user: ReturnType<typeof userEvent.setup>, current: string, next: string, confirm = next) {
  await user.type(screen.getByLabelText(/^Current password/), current)
  await user.type(screen.getByLabelText(/^New password/), next)
  await user.type(screen.getByLabelText(/^Confirm new password/), confirm)
  await user.click(screen.getByRole('button', { name: 'Change password' }))
}

const me = (must_change_password: boolean) =>
  route('GET', '/api/v1/auth/me', { body: staffUser({ must_change_password }) })

describe('ChangePasswordPage', () => {
  it('explains a forced change', async () => {
    stubApi(me(true))
    renderPage()

    expect(await screen.findByText('Your password was set by an admin. Choose a new one to continue.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Change your password' })).toBeInTheDocument()
  })

  it('does not show that line for a voluntary change', async () => {
    stubApi(me(false))
    renderPage()

    await screen.findByRole('heading', { name: 'Change your password' })
    expect(screen.queryByText(/set by an admin/)).not.toBeInTheDocument()
  })

  it('counts the new password against the 12-character minimum', async () => {
    stubApi(me(false))
    const user = renderPage()
    expect(screen.getByText('0/12 minimum')).toHaveClass('num')

    await user.type(screen.getByLabelText(/^New password/), 'abcde')

    expect(screen.getByText('5/12 minimum')).toBeInTheDocument()
  })

  it('validates length, confirmation and difference without calling the API', async () => {
    const fetchMock = stubApi(me(false))
    const user = renderPage()
    await screen.findByRole('heading', { name: 'Change your password' })
    const callsBefore = fetchMock.mock.calls.length

    await fill(user, 'old-password-123', 'short', 'different')

    expect(await screen.findByText('Use at least 12 characters.')).toBeInTheDocument()
    expect(screen.getByText('The passwords do not match.')).toBeInTheDocument()
    expect(fetchMock.mock.calls.length).toBe(callsBefore)
  })

  it('rejects a new password equal to the current one', async () => {
    stubApi(me(false))
    const user = renderPage()

    await fill(user, NEW_PASSWORD, NEW_PASSWORD)

    expect(await screen.findByText('Choose a password different from the current one.')).toBeInTheDocument()
  })

  it('shows a wrong current password on that field', async () => {
    stubApi(
      me(true),
      route('POST', '/api/v1/auth/change-password', {
        status: 400,
        body: { error: { code: 'invalid_current_password', message: 'Your current password is incorrect.', details: {} } },
      }),
    )
    const user = renderPage()

    await fill(user, 'wrong-password-1', NEW_PASSWORD)

    expect(await screen.findByText('Your current password is incorrect.')).toBeInTheDocument()
    expect(screen.getByLabelText(/^Current password/)).toHaveAttribute('aria-invalid', 'true')
  })

  it('shows the server message when rate limited', async () => {
    stubApi(
      me(true),
      route('POST', '/api/v1/auth/change-password', {
        status: 429,
        body: { error: { code: 'rate_limited', message: 'Too many failed attempts. Try again later.', details: {} } },
      }),
    )
    const user = renderPage()

    await fill(user, 'wrong-password-1', NEW_PASSWORD)

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many failed attempts. Try again later.')
  })

  it('sends both passwords and then goes to the remembered page', async () => {
    const fetchMock = stubApi(
      me(true),
      route('POST', '/api/v1/auth/change-password', { body: staffUser({ must_change_password: false }) }),
    )
    const user = renderPage('/account/password?next=%2Fjobs')

    await fill(user, 'temporary-pass-1', NEW_PASSWORD)

    expect(await screen.findByText('jobs page')).toBeInTheDocument()
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({
      current_password: 'temporary-pass-1',
      new_password: NEW_PASSWORD,
    })
  })

  it('goes to the candidate list by default and ignores an unsafe next path', async () => {
    stubApi(me(true), route('POST', '/api/v1/auth/change-password', { body: staffUser() }))
    const user = renderPage('/account/password?next=%2F%2Fevil.example')

    await fill(user, 'temporary-pass-1', NEW_PASSWORD)

    expect(await screen.findByText('candidates page')).toBeInTheDocument()
  })
})
