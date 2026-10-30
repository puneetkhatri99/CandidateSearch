import type { ReactNode } from 'react'
import { COUNTRIES } from '@/shared/data/countries'
import { FormSection, Stamp } from '@/shared/ui'
import { formatSalary, formatYears } from '@/shared/format'
import type { CandidateDetail } from '../types'

const countryName = (code: string) => COUNTRIES.find((c) => c.code === code)?.name ?? code
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

/** One row of the record: label on the left, value on the right. */
function Field({ label, mono = false, children }: { label: string; mono?: boolean; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-2.5 sm:grid-cols-[11rem_1fr] sm:gap-4">
      <dt className="caps pt-0.5 text-fg-muted">{label}</dt>
      <dd className={`min-w-0 text-fg ${mono ? 'num text-data' : ''}`}>{children || <span className="text-fg-subtle">—</span>}</dd>
    </div>
  )
}

function ExternalLink({ href }: { href: string | null }) {
  if (!href) return null
  return (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="break-all rounded-xs text-accent-fg underline underline-offset-4">
      {href}
    </a>
  )
}

function Stamps({ values, tone = 'neutral' }: { values: string[]; tone?: 'neutral' | 'brass' }) {
  if (values.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((v) => (
        <Stamp key={v} tone={tone}>
          {v}
        </Stamp>
      ))}
    </div>
  )
}

export function CandidateProfileView({ candidate: c }: { candidate: CandidateDetail }) {
  const relocation = c.open_to_relocation === null ? null : c.open_to_relocation ? 'Yes' : 'No'
  return (
    <div className="grid gap-12">
      <FormSection title="Contact">
        <dl className="-mt-2">
          <Field label="Email" mono>
            {c.email}
          </Field>
          <Field label="Phone" mono>
            {c.phone}
          </Field>
          <Field label="Location">
            {c.city}, {countryName(c.country_code)}
          </Field>
          <Field label="LinkedIn" mono>
            {c.linkedin_url && <ExternalLink href={c.linkedin_url} />}
          </Field>
          <Field label="GitHub" mono>
            {c.github_url && <ExternalLink href={c.github_url} />}
          </Field>
          <Field label="Portfolio" mono>
            {c.portfolio_url && <ExternalLink href={c.portfolio_url} />}
          </Field>
        </dl>
      </FormSection>

      <FormSection title="Professional profile">
        <dl className="-mt-2">
          <Field label="Years of experience" mono>
            {formatYears(c.years_experience)}
          </Field>
          <Field label="Skills">
            <Stamps values={c.skills} />
          </Field>
          <Field label="Summary">
            <p className="max-w-prose whitespace-pre-line">{c.summary}</p>
          </Field>
        </dl>
      </FormSection>

      <FormSection title="Experience">
        {c.experiences.length === 0 ? (
          <p className="text-sm text-fg-subtle">No experience entries.</p>
        ) : (
          <ol className="-mt-2">
            {c.experiences.map((e, i) => (
              <li key={i} className="grid gap-1 py-3 sm:grid-cols-[11rem_1fr] sm:gap-4">
                <p className="num pt-0.5 text-data text-fg-muted">
                  {e.start_month} – {e.is_current ? 'present' : e.end_month}
                </p>
                <div className="min-w-0">
                  <p className="font-medium text-fg">
                    {e.title} · {e.company}
                  </p>
                  {e.description && <p className="mt-1 max-w-prose whitespace-pre-line text-fg-muted">{e.description}</p>}
                </div>
              </li>
            ))}
          </ol>
        )}
      </FormSection>

      <FormSection title="Education">
        {c.educations.length === 0 ? (
          <p className="text-sm text-fg-subtle">No education entries.</p>
        ) : (
          <ul className="-mt-2">
            {c.educations.map((e, i) => (
              <li key={i} className="grid gap-1 py-3 sm:grid-cols-[11rem_1fr] sm:gap-4">
                <p className="num pt-0.5 text-data text-fg-muted">
                  {(e.start_year || e.end_year) && `${e.start_year ?? '?'} – ${e.end_year ?? '?'}`}
                </p>
                <div>
                  <p className="font-medium text-fg">{e.institution}</p>
                  <p className="text-fg-muted">{[e.degree, e.field_of_study].filter(Boolean).join(', ')}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </FormSection>

      <FormSection title="Preferences">
        <dl className="-mt-2">
          <Field label="Desired roles">
            <Stamps values={c.desired_roles} tone="brass" />
          </Field>
          <Field label="Work mode">
            <Stamps values={c.work_modes} tone="brass" />
          </Field>
          <Field label="Open to relocation">{relocation}</Field>
          <Field label="Notice period" mono>
            {c.notice_period_days === null ? null : `${c.notice_period_days} days`}
          </Field>
          <Field label="Expected yearly salary" mono>
            {c.expected_salary === null || c.salary_currency === null
              ? null
              : formatSalary(c.expected_salary, c.salary_currency)}
          </Field>
        </dl>
      </FormSection>

      <FormSection title="Record">
        <dl className="-mt-2">
          <Field label="Source">{c.source && <Stamp tone="brass">{c.source}</Stamp>}</Field>
          <Field label="Consent" mono>
            {dateTime.format(new Date(c.consent_given_at))} (notice {c.consent_version})
          </Field>
          <Field label="Added" mono>
            {dateTime.format(new Date(c.created_at))}
          </Field>
          <Field label="Last updated" mono>
            {dateTime.format(new Date(c.updated_at))}
          </Field>
        </dl>
      </FormSection>
    </div>
  )
}
