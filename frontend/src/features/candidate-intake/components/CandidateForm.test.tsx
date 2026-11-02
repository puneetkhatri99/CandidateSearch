import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import type { CandidateFormValues } from '../schema'
import { validFormValues } from '../testing'
import { CandidateForm } from './CandidateForm'

function renderForm(defaultValues?: Partial<CandidateFormValues>) {
  const onSubmitted = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CandidateForm onSubmitted={onSubmitted} defaultValues={defaultValues} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { onSubmitted, user: userEvent.setup() }
}

function mockFetch(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const submit = (user: ReturnType<typeof userEvent.setup>) =>
  user.click(screen.getByRole('button', { name: 'Submit profile' }))

describe('CandidateForm', () => {
  it('shows required-field errors and does not call the API when empty', async () => {
    const fetchMock = mockFetch(201, {})
    const { user } = renderForm()

    await submit(user)

    expect(await screen.findByText('Full name must be at least 2 characters.')).toBeInTheDocument()
    expect(screen.getByText('Add at least 1 skill.')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /I agree/ })).toHaveAccessibleDescription(
      'You must agree to the privacy notice to continue.',
    )
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('submits the normalized payload and reports success', async () => {
    const fetchMock = mockFetch(201, { id: 'abc', created_at: '2026-10-27T00:00:00Z' })
    const { onSubmitted, user } = renderForm(validFormValues())

    await submit(user)

    await waitFor(() => expect(onSubmitted).toHaveBeenCalledWith({ id: 'abc', created_at: '2026-10-27T00:00:00Z' }))
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/candidates')
    expect(JSON.parse(init.body as string)).toMatchObject({ email: 'asha.verma@example.com', phone: '+919876543210' })
  })

  it('fills empty fields from an uploaded resume and links it on submit', async () => {
    const extracted = {
      resume_ref: '7f9a3c1e-0000-4000-8000-000000000001',
      profile: {
        full_name: 'Priya Raman', email: 'priya@example.com', phone: null, city: 'Pune', country_code: 'IN',
        linkedin_url: null, github_url: null, portfolio_url: null, headline: 'Backend Engineer',
        years_experience: 4.5, skills: ['python'],
        experiences: [{ company: 'Nimbus', title: 'Backend Engineer', start_month: '2021-01', is_current: true, end_month: null, description: null }],
        educations: [],
      },
    }
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      const body = url === '/api/v1/resumes' ? extracted : { id: 'abc', created_at: '2026-10-27T00:00:00Z' }
      return new Response(JSON.stringify(body), { status: init.method === 'POST' && url !== '/api/v1/resumes' ? 201 : 200 })
    })
    vi.stubGlobal('fetch', fetchMock)
    // The name was typed already, so the resume's name must not replace it.
    const { onSubmitted, user } = renderForm({ ...validFormValues(), full_name: 'Typed Name', city: '', experiences: [] })

    const file = new File(['resume text'], 'cv.pdf', { type: 'application/pdf' })
    await user.upload(screen.getByLabelText('Your resume'), file)

    expect(await screen.findByText('Filled in 2 fields from the resume')).toBeInTheDocument()
    const filled = screen.getByRole('list', { name: 'Filled in from the resume' })
    expect(filled).toHaveTextContent('City')
    expect(filled).toHaveTextContent('Experience')
    expect(screen.getByLabelText(/^City/)).toHaveValue('Pune')
    expect(screen.getByLabelText(/^Full name/)).toHaveValue('Typed Name')
    expect(screen.getByLabelText(/^Company/)).toHaveValue('Nimbus')
    const [, uploadInit] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(uploadInit.body).toBe(file)
    expect(uploadInit.headers).toMatchObject({ 'X-Requested-With': 'fetch', 'Content-Type': 'application/octet-stream' })

    await submit(user)

    await waitFor(() => expect(onSubmitted).toHaveBeenCalled())
    const [, submitInit] = fetchMock.mock.calls[1] as [string, RequestInit]
    expect(JSON.parse(submitInit.body as string)).toMatchObject({ resume_ref: extracted.resume_ref, full_name: 'Typed Name' })
  })

  it('explains a resume the service could not read', async () => {
    mockFetch(422, { error: { code: 'resume_unreadable', message: 'The resume is over 4 pages.', details: {} } })
    const { user } = renderForm()

    await user.upload(screen.getByLabelText('Your resume'), new File(['x'], 'cv.pdf'))

    expect(await screen.findByRole('alert')).toHaveTextContent('The resume is over 4 pages.')
  })

  it('shows the duplicate-email message from the server on the email field', async () => {
    mockFetch(409, {
      error: { code: 'candidate_exists', message: 'A profile with this email already exists.', details: {} },
    })
    const { onSubmitted, user } = renderForm(validFormValues())

    await submit(user)

    expect(await screen.findByText('A profile with this email already exists.')).toBeInTheDocument()
    expect(screen.getByLabelText(/Email/)).toHaveAttribute('aria-invalid', 'true')
    expect(onSubmitted).not.toHaveBeenCalled()
  })

  it('maps server validation errors onto fields', async () => {
    mockFetch(422, {
      error: {
        code: 'validation_error',
        message: 'Request validation failed.',
        details: { errors: [{ loc: ['body', 'experiences', 0, 'company'], msg: 'Server says no.', type: 'x' }] },
      },
    })
    const { user } = renderForm(validFormValues())

    await submit(user)

    expect(await screen.findByText('Server says no.')).toBeInTheDocument()
    expect(screen.getByText('Please fix the highlighted fields.')).toBeInTheDocument()
  })

  it('shows a friendly message when rate limited', async () => {
    mockFetch(429, { error: { code: 'rate_limited', message: 'Too many requests.', details: {} } })
    const { user } = renderForm(validFormValues())

    await submit(user)

    expect(await screen.findByText(/Too many submissions/)).toBeInTheDocument()
  })

  it('hides the end month when the role is current', async () => {
    const { user } = renderForm(
      validFormValues({
        experiences: [{ company: 'A', title: 'T', start_month: '2021-01', is_current: false, end_month: '2022-01', description: '' }],
      }),
    )
    expect(screen.getByLabelText(/End month/)).toBeInTheDocument()

    await user.click(screen.getByLabelText('I currently work here'))

    expect(screen.queryByLabelText(/End month/)).not.toBeInTheDocument()
    expect(screen.getByText('End month: present')).toBeInTheDocument()
  })
})
