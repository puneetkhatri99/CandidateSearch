import { Controller, useFormContext } from 'react-hook-form'
import { COUNTRIES } from '@/shared/data/countries'
import { errorMessage } from '@/shared/forms/errorMessage'
import { CURRENCIES } from '@/shared/forms/salary'
import { Checkbox, FieldError, FormSection, SelectInput, TagInput, TextArea, TextInput } from '@/shared/ui'
import {
  MAX_DESIRED_ROLES,
  MAX_SKILLS,
  normalizeTag,
  type ProfileFormValues,
  type ProfilePayload,
  WORK_MODE_LABELS,
  WORK_MODES,
} from '../schema'
import { EducationFields } from './EducationFields'
import { ExperienceFields } from './ExperienceFields'

/** Every profile section. Must be rendered inside a react-hook-form FormProvider. */
export function ProfileFields() {
  const {
    register,
    control,
    formState: { errors },
  } = useFormContext<ProfileFormValues, unknown, ProfilePayload>()

  return (
    <>
      <FormSection title="About you">
        <div className="grid gap-5 sm:grid-cols-2">
          <TextInput label="Full name" required autoComplete="name" {...register('full_name')} error={errors.full_name?.message} />
          <TextInput
            label="Email"
            type="email"
            className="num"
            required
            autoComplete="email"
            {...register('email')}
            error={errors.email?.message}
          />
          <TextInput
            label="Phone"
            type="tel"
            className="num"
            autoComplete="tel"
            placeholder="+919876543210"
            hint="International format with country code."
            {...register('phone')}
            error={errors.phone?.message}
          />
          <TextInput label="City" required autoComplete="address-level2" {...register('city')} error={errors.city?.message} />
          <SelectInput label="Country" required {...register('country_code')} error={errors.country_code?.message}>
            <option value="">Select a country</option>
            {COUNTRIES.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </SelectInput>
        </div>
      </FormSection>

      <FormSection title="Links" description="Optional, but they help recruiters understand your work.">
        <TextInput
          label="LinkedIn profile"
          className="num"
          placeholder="https://www.linkedin.com/in/your-name"
          {...register('linkedin_url')}
          error={errors.linkedin_url?.message}
        />
        <TextInput
          label="GitHub profile"
          className="num"
          placeholder="https://github.com/your-username"
          {...register('github_url')}
          error={errors.github_url?.message}
        />
        <TextInput
          label="Portfolio or website"
          className="num"
          placeholder="https://your-site.dev"
          {...register('portfolio_url')}
          error={errors.portfolio_url?.message}
        />
      </FormSection>

      <FormSection title="Professional profile">
        <div className="grid gap-5 sm:grid-cols-[2fr_1fr]">
          <TextInput
            label="Headline / current title"
            required
            placeholder="e.g. Senior Backend Engineer"
            {...register('headline')}
            error={errors.headline?.message}
          />
          <TextInput
            label="Total years of experience"
            required
            inputMode="decimal"
            className="num"
            placeholder="e.g. 4.5"
            {...register('years_experience')}
            error={errors.years_experience?.message}
          />
        </div>
        <Controller
          control={control}
          name="skills"
          render={({ field }) => (
            <TagInput
              label="Skills"
              required
              name={field.name}
              value={field.value}
              onChange={field.onChange}
              onBlur={field.onBlur}
              normalize={normalizeTag}
              maxItems={MAX_SKILLS}
              placeholder="e.g. python"
              hint={`Press Enter or comma after each skill. Up to ${MAX_SKILLS}.`}
              error={errorMessage(errors.skills)}
            />
          )}
        />
        <TextArea
          label="Professional summary"
          required
          rows={6}
          hint="50–3,000 characters. What you do, what you're good at, what you're looking for."
          {...register('summary')}
          error={errors.summary?.message}
        />
      </FormSection>

      <ExperienceFields />
      <EducationFields />

      <FormSection title="Preferences">
        <Controller
          control={control}
          name="desired_roles"
          render={({ field }) => (
            <TagInput
              label="Desired roles"
              name={field.name}
              value={field.value}
              onChange={field.onChange}
              onBlur={field.onBlur}
              normalize={normalizeTag}
              maxItems={MAX_DESIRED_ROLES}
              placeholder="e.g. backend engineer"
              hint={`Up to ${MAX_DESIRED_ROLES}.`}
              error={errorMessage(errors.desired_roles)}
            />
          )}
        />
        <fieldset className="flex flex-col gap-2" aria-describedby={errors.work_modes ? 'work-modes-error' : undefined}>
          <legend className="caps mb-1 text-fg">
            Work mode<span className="text-danger-fg" aria-hidden="true"> *</span>
          </legend>
          <div className="flex flex-wrap gap-6">
            {WORK_MODES.map((mode) => (
              <Checkbox key={mode} label={WORK_MODE_LABELS[mode]} value={mode} {...register('work_modes')} />
            ))}
          </div>
          {errorMessage(errors.work_modes) && (
            <FieldError id="work-modes-error">{errorMessage(errors.work_modes)}</FieldError>
          )}
        </fieldset>
        <div className="grid gap-5 sm:grid-cols-2">
          <SelectInput label="Open to relocation" {...register('open_to_relocation')}>
            <option value="">Prefer not to say</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </SelectInput>
          <TextInput
            label="Notice period (days)"
            inputMode="numeric"
            className="num"
            placeholder="e.g. 30"
            {...register('notice_period_days')}
            error={errors.notice_period_days?.message}
          />
          <TextInput
            label="Expected yearly salary"
            inputMode="numeric"
            className="num"
            placeholder="e.g. 1800000"
            hint="Optional. Your total yearly pay expectation."
            {...register('expected_salary')}
            error={errors.expected_salary?.message}
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
    </>
  )
}
