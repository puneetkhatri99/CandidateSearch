import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route, staffUser, stubApi } from '@/test/fakeApi'
import { PublicLayout, RootLayout } from './RootLayout'

function renderAt(path: string, role: 'admin' | 'recruiter', mustChangePassword = false) {
  stubApi(route('GET', '/api/v1/auth/me', { body: staffUser({ role, must_change_password: mustChangePassword }) }))
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<RootLayout />}>
            <Route path="/jobs" element={<p>jobs</p>} />
            <Route path="/jobs/new" element={<p>new job</p>} />
            <Route path="/jobs/:id" element={<p>one job</p>} />
            <Route path="/admin/users" element={<p>users</p>} />
          </Route>
          <Route element={<PublicLayout />}>
            <Route path="/account/password" element={<p>password</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const sidebar = () => screen.getByRole('navigation', { name: 'Main' })
const labels = () => Array.from(sidebar().querySelectorAll('a')).map((link) => link.textContent)

describe('RootLayout navigation', () => {
  it('lists the staff pages in order, with Users and System under Settings', async () => {
    renderAt('/jobs', 'admin')

    await screen.findByText('Staff Member')

    expect(labels()).toEqual(['Candidates', 'Add candidate', 'Bookmarks', 'Jobs', 'Add job', 'AI spending', 'Settings'])
  })

  it('marks Settings active on the pages it opens', async () => {
    renderAt('/admin/users', 'admin')

    expect(await screen.findByRole('link', { name: 'Settings' })).toHaveAttribute('aria-current', 'page')
  })

  it('shows no API status line in the sidebar', async () => {
    renderAt('/jobs', 'recruiter')

    await screen.findByText('Staff Member')

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('marks Add job active on /jobs/new and Jobs active on other job paths', async () => {
    renderAt('/jobs/new', 'recruiter')
    expect(await screen.findByRole('link', { name: 'Add job' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Jobs' })).not.toHaveAttribute('aria-current')
  })

  it('marks Jobs active on a job detail page', async () => {
    renderAt('/jobs/abc', 'recruiter')

    expect(await screen.findByRole('link', { name: 'Jobs' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Add job' })).not.toHaveAttribute('aria-current')
  })

})

describe('PublicLayout navigation', () => {
  it('hides the Candidates link while a password change is pending', async () => {
    renderAt('/account/password', 'recruiter', true)

    await screen.findByText('Staff Member')

    expect(screen.queryByRole('link', { name: 'Candidates' })).not.toBeInTheDocument()
  })

  it('shows it for a normal session', async () => {
    renderAt('/account/password', 'recruiter', false)

    expect(await screen.findByRole('link', { name: 'Candidates' })).toBeInTheDocument()
  })
})
