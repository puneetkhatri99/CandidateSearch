import { zodResolver } from '@hookform/resolvers/zod'
import { Controller, FormProvider, useForm, useFormContext, useWatch } from 'react-hook-form'
import { WORK_MODE_LABELS, WORK_MODES } from '@/features/candidate-profile'
import { COUNTRIES } from '@/shared/data/countries'
import { errorMessage } from '@/shared/forms/errorMessage'
import { CURRENCIES } from '@/shared/forms/salary'
import { normalizeTag } from '@/shared/forms/tags'
import { Alert, Button, FormSection, SelectInput, TagInput, TextArea, TextInput } from '@/shared/ui'
import {
  EMPLOYMENT_TYPE_LABELS,
  EMPLOYMENT_TYPES,
  JOB_STATUS_LABELS,
  JOB_STATUSES,
  type JobFormValues,
  type JobPayload,
  jobSchema,
  MAX_DESCRIPTION_LENGTH,
  MAX_SKILLS,
  MIN_DESCRIPTION_LENGTH,
} from '../schema'
import { applyJobServerError, CONFLICT_MESSAGE } from '../serverErrors'

interface JobFormProps {
  defaultValues: JobFormValues
  submitLabel: string
  onSubmit: (payload: JobPayload) => Promise<unknown>
  onCancel: () => void
  /** Offered next to a version-conflict message; discards the edits and loads the latest job. */
  onReloadLatest?: () => void
}

const codePointCount = (value: string) => [...value].length

/**
 * A child of the form, so it registers after the tag lists above it: react-hook-form focuses
 * the first invalid field in registration order, and parents register before their children.
 */
function DescriptionSection() {
  const {
    register,
    control,
    formState: { errors },
  } = useFormContext<JobFormValues, unknown, JobPayload>()
  const length = codePointCount(useWatch({ control, name: 'description' }))

  return (
    <FormSection title="Description">
      <div className="grid gap-1.5">
        <TextArea
          label="Job description"
          required
          rows={12}
          hint={`${MIN_DESCRIPTION_LENGTH}–${MAX_DESCRIPTION_LENGTH.toLocaleString('en-US')} characters, plain text. Don't include names or contact details.`}
          {...register('description')}
          error={errors.description?.message}
        />
        <p className="num text-xs text-fg-subtle" aria-live="polite">
          {String(length).padStart(4, '0')} / {MAX_DESCRIPTION_LENGTH.toLocaleString('en-US')}
        </p>
      </div>
    </FormSection>
  )
}

/** A child for the same reason as DescriptionSection: its fields come after the skill lists. */
function PaySection() {
  const {
    register,
    formState: { errors },
  } = useFormContext<JobFormValues, unknown, JobPayload>()

  return (
    <FormSection title="Pay" description="Optional. Yearly, before tax. Leave one end empty for an open range.">
      <div className="grid gap-5 sm:grid-cols-3">
        <TextInput
          label="Minimum yearly pay"
          inputMode="numeric"
          className="num"
          placeholder="e.g. 1500000"
          {...register('salary_min')}
          error={errors.salary_min?.message}
        />
        <TextInput
          label="Maximum yearly pay"
          inputMode="numeric"
          className="num"
          placeholder="e.g. 2400000"
          {...register('salary_max')}
          error={errors.salary_max?.message}
        />
        <SelectInput label="Currency" {...register('salary_currency')} error={errors.salary_currency?.message}>
          <option value="">Select a currency</option>
          {CURRENCIES.map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </SelectInput>
      </div>
    </FormSection>
  )
}

export function JobForm({ defaultValues, submitLabel, onSubmit, onCancel, onReloadLatest }: JobFormProps) {
  const form = useForm<JobFormValues, unknown, JobPayload>({
    resolver: zodResolver(jobSchema),
    defaultValues,
    mode: 'onTouched',
  })
  const {
    register,
    control,
    setError,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = form
  const remote = useWatch({ control, name: 'work_mode' }) === 'remote'

  const submit = async (payload: JobPayload) => {
    try {
      await onSubmit(payload)
    } catch (error) {
      applyJobServerError(error, setError)
    }
  }

  return (
    <FormProvider {...form}>
      <form onSubmit={handleSubmit(submit)} noValidate className="grid gap-10">
        <FormSection title="Role">
          <div className="grid gap-5 sm:grid-cols-2">
            <TextInput label="Job title" required {...register('title')} error={errors.title?.message} />
            <TextInput label="Department" {...register('department')} error={errors.department?.message} />
            <SelectInput label="Employment type" required {...register('employment_type')} error={errors.employment_type?.message}>
              {EMPLOYMENT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {EMPLOYMENT_TYPE_LABELS[type]}
                </option>
              ))}
            </SelectInput>
            <SelectInput label="Status" required {...register('status')} error={errors.status?.message}>
              {JOB_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {JOB_STATUS_LABELS[status]}
                </option>
              ))}
            </SelectInput>
          </div>
        </FormSection>

        <FormSection title="Location">
          <div className="grid gap-5 sm:grid-cols-3">
            <SelectInput label="Work mode" required {...register('work_mode')} error={errors.work_mode?.message}>
              {WORK_MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {WORK_MODE_LABELS[mode]}
                </option>
              ))}
            </SelectInput>
            <TextInput
              label="City"
              required={!remote}
              hint={remote ? 'Optional for remote roles.' : undefined}
              {...register('city')}
              error={errors.city?.message}
            />
            <SelectInput label="Country" required={!remote} {...register('country_code')} error={errors.country_code?.message}>
              <option value="">{remote ? 'Anywhere' : 'Select a country'}</option>
              {COUNTRIES.map((country) => (
                <option key={country.code} value={country.code}>
                  {country.name}
                </option>
              ))}
            </SelectInput>
          </div>
        </FormSection>

        <FormSection title="Requirements">
          <div className="grid gap-5 sm:grid-cols-2">
            <TextInput
              label="Minimum years of experience"
              required
              inputMode="decimal"
              className="num"
              placeholder="e.g. 3"
              {...register('min_years')}
              error={errors.min_years?.message}
            />
            <TextInput
              label="Maximum years of experience"
              inputMode="decimal"
              className="num"
              placeholder="e.g. 6"
              hint="Leave empty for no upper limit."
              {...register('max_years')}
              error={errors.max_years?.message}
            />
          </div>
          <Controller
            control={control}
            name="must_have_skills"
            render={({ field }) => (
              <TagInput
                label="Must-have skills"
                required
                name={field.name}
                value={field.value}
                onChange={field.onChange}
                onBlur={field.onBlur}
                normalize={normalizeTag}
                maxItems={MAX_SKILLS}
                placeholder="e.g. python"
                hint={`Press Enter or comma after each skill. Up to ${MAX_SKILLS}.`}
                error={errorMessage(errors.must_have_skills)}
              />
            )}
          />
          <Controller
            control={control}
            name="nice_to_have_skills"
            render={({ field }) => (
              <TagInput
                label="Nice-to-have skills"
                name={field.name}
                value={field.value}
                onChange={field.onChange}
                onBlur={field.onBlur}
                normalize={normalizeTag}
                maxItems={MAX_SKILLS}
                placeholder="e.g. kubernetes"
                hint={`Up to ${MAX_SKILLS}. A skill can't be in both lists.`}
                error={errorMessage(errors.nice_to_have_skills)}
              />
            )}
          />
        </FormSection>

        <PaySection />
        <DescriptionSection />

        {errors.root?.server?.message && (
          <Alert>
            {errors.root.server.message}
            {onReloadLatest && errors.root.server.message === CONFLICT_MESSAGE && (
              <button type="button" className="ml-2 font-medium underline" onClick={onReloadLatest}>
                Discard my changes and reload
              </button>
            )}
          </Alert>
        )}
        <div className="flex gap-3">
          <Button variant="secondary" onClick={onCancel} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Saving…' : submitLabel}
          </Button>
        </div>
      </form>
    </FormProvider>
  )
}
