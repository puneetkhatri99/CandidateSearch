/** Tag handling shared by every form with a skills-style tag list (matches the backend). */
import { z } from 'zod'

export const normalizeTag = (value: string) => value.split(/\s+/).filter(Boolean).join(' ').toLowerCase()

export const normalizeTags = (values: string[]) => [...new Set(values.map(normalizeTag).filter(Boolean))]

/** Trims, lower-cases and de-duplicates, then checks the count and length of the cleaned list. */
export const tagList = (label: string, min: number, max: number, maxLength: number) =>
  z
    .array(z.string())
    .transform(normalizeTags)
    .pipe(
      z
        .array(z.string().max(maxLength, `Each ${label} must be at most ${maxLength} characters.`))
        .min(min, `Add at least ${min} ${label}.`)
        .max(max, `Add at most ${max} ${label}s.`),
    )
