import { useFieldArray, useFormContext } from 'react-hook-form'
import { Button, FormSection, TextInput } from '@/shared/ui'
import { type ProfileFormValues, type ProfilePayload, emptyEducation, MAX_EDUCATIONS } from '../schema'

export function EducationFields() {
  const {
    control,
    register,
    formState: { errors },
  } = useFormContext<ProfileFormValues, unknown, ProfilePayload>()
  const { fields, append, remove } = useFieldArray({ control, name: 'educations' })

  return (
    <FormSection title="Education" description={`Optional, up to ${MAX_EDUCATIONS} entries.`}>
      {fields.map((field, index) => {
        const fieldErrors = errors.educations?.[index]
        return (
          <div key={field.id} className="grid gap-4 rounded-md bg-surface-muted p-5 sm:grid-cols-2">
            <p className="num text-data text-fg-muted sm:col-span-2">Education {index + 1}</p>
            <div className="sm:col-span-2">
              <TextInput
                label="Institution"
                required
                {...register(`educations.${index}.institution`)}
                error={fieldErrors?.institution?.message}
              />
            </div>
            <TextInput
              label="Degree"
              placeholder="e.g. B.Tech"
              {...register(`educations.${index}.degree`)}
              error={fieldErrors?.degree?.message}
            />
            <TextInput
              label="Field of study"
              placeholder="e.g. Computer Science"
              {...register(`educations.${index}.field_of_study`)}
              error={fieldErrors?.field_of_study?.message}
            />
            <TextInput
              label="Start year"
              inputMode="numeric"
              className="num"
              placeholder="YYYY"
              {...register(`educations.${index}.start_year`)}
              error={fieldErrors?.start_year?.message}
            />
            <TextInput
              label="End year (or expected)"
              inputMode="numeric"
              className="num"
              placeholder="YYYY"
              {...register(`educations.${index}.end_year`)}
              error={fieldErrors?.end_year?.message}
            />
            <div className="sm:col-span-2">
              <Button variant="danger" onClick={() => remove(index)}>
                Remove education {index + 1}
              </Button>
            </div>
          </div>
        )
      })}
      <div>
        <Button variant="secondary" onClick={() => append(emptyEducation())} disabled={fields.length >= MAX_EDUCATIONS}>
          Add education
        </Button>
      </div>
    </FormSection>
  )
}
