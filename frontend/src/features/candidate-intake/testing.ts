import type { CandidateFormValues } from './schema'

/** A complete, valid form state for tests. */
export const validFormValues = (overrides: Partial<CandidateFormValues> = {}): CandidateFormValues => ({
  full_name: 'Asha Verma',
  email: 'Asha.Verma@Example.com',
  phone: '+91 98765 43210',
  city: 'Bengaluru',
  country_code: 'IN',
  linkedin_url: 'linkedin.com/in/asha-verma',
  github_url: '',
  portfolio_url: '',
  headline: 'Senior Backend Engineer',
  years_experience: '6.5',
  skills: ['python', 'fastapi'],
  summary: 'Backend engineer building APIs and data pipelines for fintech products at scale.',
  experiences: [
    {
      company: 'Acme',
      title: 'Engineer',
      start_month: '2021-03',
      is_current: true,
      end_month: '',
      description: '',
    },
  ],
  educations: [],
  desired_roles: [],
  work_modes: ['remote'],
  open_to_relocation: 'yes',
  notice_period_days: '30',
  expected_salary: '18,00,000',
  salary_currency: 'INR',
  consent: true,
  website: '',
  ...overrides,
})
