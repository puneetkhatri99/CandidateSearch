import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/shared/api/client'
import { emptyJob, type JobFormValues, type JobPayload } from '../schema'
import { validJobValues } from '../testing'
import { JobForm } from './JobForm'

function renderForm(defaultValues: JobFormValues, onSubmit: (payload: JobPayload) => Promise<unknown> = () => Promise.resolve()) {
  const handleSubmit = vi.fn(onSubmit)
  render(<JobForm defaultValues={defaultValues} submitLabel="Add job" onSubmit={handleSubmit} onCancel={vi.fn()} />)
  return { onSubmit: handleSubmit, user: userEvent.setup() }
}

const submit = (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole('button', { name: 'Add job' }))

const validationError = (errors: Array<{ loc: Array<string | number>; msg: string }>) =>
  new ApiError(422, 'validation_error', 'Request validation failed.', { errors })

describe('JobForm', () => {
  it('shows required-field errors and does not submit an empty form', async () => {
    const { onSubmit, user } = renderForm(emptyJob())

    await submit(user)

    expect(await screen.findByText('Job title is required.')).toBeInTheDocument()
    expect(screen.getByText('Add at least 1 skill.')).toBeInTheDocument()
    expect(screen.getByText('Description must be at least 100 characters.')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('focuses the first invalid field in page order', async () => {
    const { user } = renderForm(emptyJob())

    await submit(user)

    await waitFor(() => expect(screen.getByLabelText(/Job title/)).toHaveFocus())
  })

  it('focuses the description when it is the only invalid text field', async () => {
    const { user } = renderForm(validJobValues({ description: 'too short' }))

    await submit(user)

    await waitFor(() => expect(screen.getByLabelText(/Job description/)).toHaveFocus())
  })

  it('marks the location optional for a remote job', async () => {
    const { user } = renderForm(validJobValues({ work_mode: 'hybrid' }))
    expect(screen.getByLabelText(/^City/)).toBeRequired()

    await user.selectOptions(screen.getByLabelText(/Work mode/), 'remote')

    expect(screen.getByLabelText(/^City/)).not.toBeRequired()
    expect(screen.getByLabelText(/^Country/)).not.toBeRequired()
    expect(screen.getByText('Optional for remote roles.')).toBeInTheDocument()
  })

  it('submits the normalised payload', async () => {
    const { onSubmit, user } = renderForm(validJobValues({ must_have_skills: ['Python', 'python'], max_years: '' }))

    await submit(user)

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({
      title: 'Senior Backend Engineer',
      must_have_skills: ['python'],
      min_years: 3,
      max_years: null,
      country_code: 'DE',
      status: 'draft',
    })
  })

  it('maps server validation errors onto fields', async () => {
    const { user } = renderForm(validJobValues(), () =>
      Promise.reject(validationError([{ loc: ['body', 'max_years'], msg: 'Server says no.' }])),
    )

    await submit(user)

    expect(await screen.findByText('Server says no.')).toBeInTheDocument()
    expect(screen.getByText('Please fix the highlighted fields.')).toBeInTheDocument()
    expect(screen.getByLabelText(/Maximum years/)).toHaveAttribute('aria-invalid', 'true')
  })

  it('shows the conflict message when the job was changed by someone else', async () => {
    const { user } = renderForm(validJobValues(), () =>
      Promise.reject(new ApiError(409, 'version_conflict', 'conflict', {})),
    )

    await submit(user)

    expect(
      await screen.findByText(/This job was changed by someone else\. Reload to see the latest version\./),
    ).toBeInTheDocument()
  })

  it('counts the description with a zero-padded mono counter', async () => {
    const { user } = renderForm(emptyJob())
    expect(screen.getByText('0000 / 10,000')).toBeInTheDocument()

    await user.type(screen.getByLabelText(/Job description/), 'hello')

    expect(screen.getByText('0005 / 10,000')).toHaveClass('num')
  })
})
