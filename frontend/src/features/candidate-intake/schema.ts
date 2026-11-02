/** Public intake form = the shared profile + consent + honeypot. */
import { z } from 'zod'
import { candidateProfileSchema, emptyProfile } from '@/features/candidate-profile'

export const candidateFormSchema = candidateProfileSchema.extend({
  consent: z.boolean().refine((v) => v, 'You must agree to the privacy notice to continue.'),
  website: z.string(),
  // Set by ResumeUpload; links the uploaded resume to the new profile.
  resume_ref: z.string().transform((v) => (v === '' ? null : v)),
})

export type CandidateFormValues = z.input<typeof candidateFormSchema>
export type CandidatePayload = z.output<typeof candidateFormSchema>

export const emptyCandidateForm = (): CandidateFormValues => ({
  ...emptyProfile(),
  consent: false,
  website: '',
  resume_ref: '',
})
