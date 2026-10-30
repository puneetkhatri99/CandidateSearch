import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { route, stubApi } from '@/test/fakeApi'
import { userAccount } from '../testing'
import { CreateUserDialog } from './CreateUserDialog'

function renderDialog() {
  const onClose = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CreateUserDialog open onClose={onClose} />
    </QueryClientProvider>,
  )
  return { onClose, user: userEvent.setup() }
}

const fillIdentity = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.type(screen.getByLabelText(/^Email/), 'New.Person@Example.com')
  await user.type(screen.getByLabelText(/^Full name/), 'New Person')
}

describe('CreateUserDialog', () => {
  it('defaults the role to recruiter', () => {
    renderDialog()

    expect(screen.getByLabelText('Role')).toHaveValue('recruiter')
  })

  it('generates a 16-character password shown in the open', async () => {
    const { user } = renderDialog()
    const field = screen.getByLabelText(/Temporary password/) as HTMLInputElement
    expect(field).toHaveClass('num')
    expect(field).toHaveAttribute('type', 'text')

    await user.click(screen.getByRole('button', { name: 'Generate' }))

    expect(field.value).toHaveLength(16)
  })

  it('generates a different password each time', async () => {
    const { user } = renderDialog()
    const field = screen.getByLabelText(/Temporary password/) as HTMLInputElement

    await user.click(screen.getByRole('button', { name: 'Generate' }))
    const first = field.value
    await user.click(screen.getByRole('button', { name: 'Generate' }))

    expect(field.value).not.toBe(first)
  })

  it('validates before calling the API', async () => {
    const fetchMock = stubApi()
    const { user } = renderDialog()

    await user.click(screen.getByRole('button', { name: 'Add account' }))

    expect(await screen.findByText('Enter a valid email address.')).toBeInTheDocument()
    expect(screen.getByText('Use at least 12 characters.')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('creates the account with a lower-cased email and closes', async () => {
    const fetchMock = stubApi(route('POST', '/api/v1/admin/users', { status: 201, body: userAccount() }))
    const { onClose, user } = renderDialog()
    await fillIdentity(user)
    await user.click(screen.getByRole('button', { name: 'Generate' }))
    const password = (screen.getByLabelText(/Temporary password/) as HTMLInputElement).value

    await user.click(screen.getByRole('button', { name: 'Add account' }))

    await vi.waitFor(() => expect(onClose).toHaveBeenCalled())
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({
      email: 'new.person@example.com',
      full_name: 'New Person',
      role: 'recruiter',
      temporary_password: password,
    })
  })

  it('shows a duplicate email on the email field and stays open', async () => {
    stubApi(
      route('POST', '/api/v1/admin/users', {
        status: 409,
        body: { error: { code: 'user_exists', message: 'A user with this email already exists.', details: {} } },
      }),
    )
    const { onClose, user } = renderDialog()
    await fillIdentity(user)
    await user.click(screen.getByRole('button', { name: 'Generate' }))

    await user.click(screen.getByRole('button', { name: 'Add account' }))

    expect(await screen.findByText('A user with this email already exists.')).toBeInTheDocument()
    expect(screen.getByLabelText(/^Email/)).toHaveAttribute('aria-invalid', 'true')
    expect(onClose).not.toHaveBeenCalled()
  })
})
