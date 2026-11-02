import { Link } from 'react-router'
import { formatSalary } from '@/shared/format'
import { Stamp, type StampTone } from '@/shared/ui'
import { type CandidateSummary, type Criterion, FILTER_LABELS, type SemanticMatch } from '../types'
import { BookmarkButton } from './BookmarkButton'

type Fit = NonNullable<SemanticMatch['fit']>
const FIT_LABELS: Record<Fit, string> = { strong: 'Strong match', partial: 'Partial match', weak: 'Weak match' }
const FIT_TONES: Record<Fit, StampTone> = { strong: 'success', partial: 'brass', weak: 'neutral' }
const CRITERION_LABELS: Record<Criterion['name'], string> = {
  skills: 'Skills',
  location: 'Location',
  experience: 'Experience',
  salary: 'Salary',
}
const STATUS_MARKS: Record<Criterion['status'], string> = { met: '✓', partial: '~', missed: '✗' }
const STATUS_CLASSES: Record<Criterion['status'], string> = {
  met: 'text-success-fg',
  partial: 'text-warning-fg',
  missed: 'text-danger-fg',
}
const STATUS_WORDS: Record<Criterion['status'], string> = { met: 'met', partial: 'partly met', missed: 'not met' }

interface MatchCardProps {
  match: SemanticMatch
  /** Position in the AI's ranking; absent when it couldn't rank, and for filtered-out people. */
  rank?: number
  onDelete?: (candidate: CandidateSummary) => void
}

/** One search result as a short case for the person: who they are and why they fit. */
export function MatchCard({ match, rank, onDelete }: MatchCardProps) {
  const c = match.candidate
  const facts = [
    c.headline,
    `${c.city}, ${c.country_code}`,
    `${c.years_experience.toFixed(1)} yrs`,
    ...(c.expected_salary === null || c.salary_currency === null ? [] : [formatSalary(c.expected_salary, c.salary_currency)]),
  ]

  return (
    <li className="grid grid-cols-[1.75rem_minmax(0,1fr)] py-4">
      <span className="num pt-0.5 text-fg-muted">{rank}</span>
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Link
            to={`/admin/candidates/${c.id}`}
            className="rounded-xs text-base font-semibold text-accent-fg underline-offset-4 hover:underline"
          >
            {c.full_name}
          </Link>
          {match.fit && <Stamp tone={FIT_TONES[match.fit]}>{FIT_LABELS[match.fit]}</Stamp>}
          <div className="ml-auto flex items-center gap-4 text-sm">
            <BookmarkButton candidate={c} />
            <Link
              to={`/admin/candidates/${c.id}?edit=1`}
              className="rounded-xs font-medium text-fg-muted underline-offset-4 hover:text-fg hover:underline"
              aria-label={`Edit ${c.full_name}`}
            >
              Edit
            </Link>
            {onDelete && (
              <button
                type="button"
                onClick={() => onDelete(c)}
                className="rounded-xs font-medium text-danger-fg underline-offset-4 hover:underline"
                aria-label={`Delete ${c.full_name}`}
              >
                Delete
              </button>
            )}
          </div>
        </div>
        <p className="num text-fg-muted">{facts.join(' · ')}</p>
        {match.failed_filters.length > 0 && (
          <p className="text-sm text-danger-fg">
            Fails filter: {match.failed_filters.map((name) => FILTER_LABELS[name]).join(', ')}
          </p>
        )}
        {match.criteria.length > 0 ? (
          <ul className="grid gap-1">
            {match.criteria.map((criterion) => (
              <li key={criterion.name} className="grid grid-cols-[1rem_5.5rem_minmax(0,1fr)] gap-x-1">
                <span aria-hidden="true" className={STATUS_CLASSES[criterion.status]}>
                  {STATUS_MARKS[criterion.status]}
                </span>
                <span className="sr-only">{STATUS_WORDS[criterion.status]}: </span>
                <span className="font-medium text-fg">
                  {CRITERION_LABELS[criterion.name]}
                  <span className="sr-only">: </span>
                </span>
                <span className="text-fg-muted">{criterion.note}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="flex flex-wrap gap-1">
            {c.top_skills.map((skill) => (
              <Stamp key={skill}>{skill}</Stamp>
            ))}
          </div>
        )}
      </div>
    </li>
  )
}
