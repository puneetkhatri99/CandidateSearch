import { useFieldArray, useFormContext, useWatch } from 'react-hook-form'
import { Button, Checkbox, FieldError, FormSection, TextArea, TextInput } from '@/shared/ui'
import {
  type ProfileFormValues,
  type ProfilePayload,
  currentMonth,
  emptyExperience,
  MAX_EXPERIENCES,
} from '../schema'

export function ExperienceFields() {
  const {
    control,
    register,
    setValue,
    formState: { errors },
  } = useFormContext<ProfileFormValues, unknown, ProfilePayload>()
  const { fields, append, remove } = useFieldArray({ control, name: 'experiences' })
  const values = useWatch({ control, name: 'experiences' })
  const maxMonth = currentMonth()
  // Only list-level errors (e.g. two current roles); item errors are shown on their fields.
  const listError = errors.experiences?.root?.message ?? errors.experiences?.message

  return (
    <FormSection title="Experience" description={`Most recent first. Optional, up to ${MAX_EXPERIENCES} roles.`}>
      {fields.map((field, index) => {
        const fieldErrors = errors.experiences?.[index]
        const isCurrent = values[index]?.is_current ?? false
        return (
          <div key={field.id} className="grid gap-4 rounded-md bg-surface-muted p-5 sm:grid-cols-2">
            <p className="num text-data text-fg-muted sm:col-span-2">Role {index + 1}</p>
            <TextInput
              label="Company"
              required
              {...register(`experiences.${index}.company`)}
              error={fieldErrors?.company?.message}
            />
            <TextInput
              label="Title"
              required
              {...register(`experiences.${index}.title`)}
              error={fieldErrors?.title?.message}
            />
            <TextInput
              type="month"
              className="num"
              label="Start month"
              required
              max={maxMonth}
              placeholder="YYYY-MM"
              {...register(`experiences.${index}.start_month`)}
              error={fieldErrors?.start_month?.message}
            />
            {isCurrent ? (
              <div className="flex flex-col justify-end pb-2 text-sm text-fg-muted">End month: present</div>
            ) : (
              <TextInput
                type="month"
                className="num"
                label="End month"
                required
                max={maxMonth}
                placeholder="YYYY-MM"
                {...register(`experiences.${index}.end_month`)}
                error={fieldErrors?.end_month?.message}
              />
            )}
            <div className="sm:col-span-2">
              <Checkbox
                label="I currently work here"
                {...register(`experiences.${index}.is_current`, {
                  onChange: (event: { target: { checked: boolean } }) => {
                    if (event.target.checked) setValue(`experiences.${index}.end_month`, '')
                  },
                })}
              />
            </div>
            <div className="sm:col-span-2">
              <TextArea
                label="Description"
                hint="What you built or owned. Up to 2,000 characters."
                {...register(`experiences.${index}.description`)}
                error={fieldErrors?.description?.message}
              />
            </div>
            <div className="sm:col-span-2">
              <Button variant="danger" onClick={() => remove(index)}>
                Remove role {index + 1}
              </Button>
            </div>
          </div>
        )
      })}
      {listError && <FieldError>{listError}</FieldError>}
      <div>
        <Button
          variant="secondary"
          onClick={() => append(emptyExperience())}
          disabled={fields.length >= MAX_EXPERIENCES}
        >
          Add experience
        </Button>
      </div>
    </FormSection>
  )
}
