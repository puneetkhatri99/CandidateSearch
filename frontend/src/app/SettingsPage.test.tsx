import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { route, staffUser, stubApi } from '@/test/fakeApi'
import { SettingsPage } from './SettingsPage'

function renderAs(role: 'admin' | 'recruiter') {
  stubApi(route('GET', '/api/v1/auth/me', { body: staffUser({ role }) }))
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('SettingsPage', () => {
  it('offers password, users and system to an admin', async () => {
    renderAs('admin')

    expect(await screen.findByRole('link', { name: 'Users' })).toHaveAttribute('href', '/admin/users')
    // Back to Settings after saving the new password.
    expect(screen.getByRole('link', { name: 'Change password' })).toHaveAttribute('href', '/account/password?next=%2Fsettings')
    expect(screen.getByRole('link', { name: 'System' })).toHaveAttribute('href', '/admin/system')
    expect(screen.getByRole('link', { name: 'Saved searches' })).toHaveAttribute('href', '/settings/searches')
  })

  it('leaves Users out for a recruiter', async () => {
    renderAs('recruiter')

    await screen.findByRole('link', { name: 'System' })

    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument()
  })
})
