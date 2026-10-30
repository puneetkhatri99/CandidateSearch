import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route, staffUser, stubApi } from '@/test/fakeApi'
import { RequireAuth } from './RequireAuth'
import { RequireRole } from './RequireRole'

function Where() {
  const location = useLocation()
  return <p>{`at ${location.pathname}${location.search}`}</p>
}

function renderAt(path: string) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<p>login page</p>} />
          <Route element={<RequireAuth />}>
            <Route path="/account/password" element={<Where />} />
            <Route path="/admin/candidates" element={<Where />} />
            <Route element={<RequireRole role="admin" />}>
              <Route path="/admin/users" element={<p>users page</p>} />
            </Route>
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const me = (overrides?: Record<string, unknown>) => route('GET', '/api/v1/auth/me', { body: staffUser(overrides) })

describe('RequireAuth', () => {
  it('sends a signed-out visitor to the login page', async () => {
    stubApi(route('GET', '/api/v1/auth/me', { status: 401, body: { error: { code: 'not_authenticated', message: 'No', details: {} } } }))
    renderAt('/admin/candidates')

    expect(await screen.findByText('login page')).toBeInTheDocument()
  })

  it('lets a signed-in user through', async () => {
    stubApi(me())
    renderAt('/admin/candidates')

    expect(await screen.findByText('at /admin/candidates')).toBeInTheDocument()
  })

  it('redirects a user with a pending password change to the change-password page, remembering the target', async () => {
    stubApi(me({ must_change_password: true }))
    renderAt('/admin/candidates?q=python')

    expect(await screen.findByText('at /account/password?next=%2Fadmin%2Fcandidates%3Fq%3Dpython')).toBeInTheDocument()
  })

  it('lets that user stay on the change-password page', async () => {
    stubApi(me({ must_change_password: true }))
    renderAt('/account/password')

    expect(await screen.findByText('at /account/password')).toBeInTheDocument()
  })
})

describe('RequireRole', () => {
  it('blocks recruiters from admin pages with an explanation', async () => {
    stubApi(me({ role: 'recruiter' }))
    renderAt('/admin/users')

    expect(await screen.findByRole('alert')).toHaveTextContent('Only admins can manage staff accounts.')
    expect(screen.queryByText('users page')).not.toBeInTheDocument()
  })

  it('lets admins in', async () => {
    stubApi(me({ role: 'admin' }))
    renderAt('/admin/users')

    expect(await screen.findByText('users page')).toBeInTheDocument()
  })
})
