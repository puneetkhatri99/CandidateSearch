import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { Stamp } from '@/shared/ui'
import { formatSalary, formatYears } from '@/shared/format'
import { type CandidateSummary, type Criterion, FILTER_LABELS, type SemanticMatch } from '../types'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

const COLUMNS = ['Name', 'Email', 'Headline', 'Location', 'Years', 'Expected pay', 'Top skills', 'Source', 'Added', 'Actions']
const SKELETON_ROWS = 6
const cell = 'px-3 py-4 align-top'

type Fit = NonNullable<SemanticMatch['fit']>
const FIT_LABELS: Record<Fit, string> = { strong: 'Strong', partial: 'Partial', weak: 'Weak' }
const FIT_CLASSES: Record<Fit, string> = {
  strong: 'text-success-fg',
  partial: 'text-fg',
  weak: 'text-fg-muted',
}
const CRITERION_LABELS: Record<Criterion['name'], string> = {
  skills: 'Skills',
  location: 'Location',
  experience: 'Experience',
  salary: 'Salary',
}
const STATUS_MARKS: Record<Criterion['status'], string> = { met: '✓', partial: '~', missed: '✗' }
const STATUS_WORDS: Record<Criterion['status'], string> = { met: 'met', partial: 'partly met', missed: 'not met' }

function MatchCell({ match }: { match: SemanticMatch | undefined }) {
  if (!match) return '—'
  const failed = match.failed_filters.length > 0 && (
    <span className="text-xs text-danger-fg">
      Fails filter: {match.failed_filters.map((name) => FILTER_LABELS[name]).join(', ')}
    </span>
  )
  if (match.fit == null) return failed || '—'
  return (
    <div className="grid min-w-56 gap-1">
      <span className={`font-medium ${FIT_CLASSES[match.fit]}`}>{FIT_LABELS[match.fit]}</span>
      {failed}
      <ul className="grid gap-0.5 text-xs text-fg-muted">
        {match.criteria.map((criterion) => (
          <li key={criterion.name}>
            <span aria-hidden="true">{STATUS_MARKS[criterion.status]} </span>
            <span className="sr-only">{STATUS_WORDS[criterion.status]}: </span>
            {CRITERION_LABELS[criterion.name]}: {criterion.note}
          </li>
        ))}
      </ul>
    </div>
  )
}

const MATCH_COLUMN = 'Match'
const RIGHT_ALIGNED = new Set(['Years', 'Expected pay'])

interface CandidateTableProps {
  candidates: CandidateSummary[]
  /** Omitted for users who may not delete; the Delete action is then hidden. */
  onDelete?: (candidate: CandidateSummary) => void
  /** Results of a search by meaning, by candidate id; adds a Match column. */
  matches?: ReadonlyMap<string, SemanticMatch>
  /** Screen-reader name, needed when a page shows more than one table. */
  caption?: string
}

function columnsFor(withMatch: boolean) {
  // The match score sits right after the name it belongs to.
  return withMatch ? ['Name', MATCH_COLUMN, ...COLUMNS.slice(1)] : COLUMNS
}

const DEFAULT_CAPTION = 'Candidates matching your search'

function TableShell({
  children,
  withMatch = false,
  caption = DEFAULT_CAPTION,
}: {
  children: ReactNode
  withMatch?: boolean
  caption?: string
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left">
        <caption className="sr-only">{caption}</caption>
        <thead className="border-b border-border text-fg-muted">
          <tr>
            {columnsFor(withMatch).map((column) => (
              <th
                key={column}
                scope="col"
                className={`caps whitespace-nowrap px-3 py-3 ${RIGHT_ALIGNED.has(column) ? 'text-right' : ''}`}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">{children}</tbody>
      </table>
    </div>
  )
}

export function CandidateTableSkeleton({ withMatch = false }: { withMatch?: boolean }) {
  return (
    <div role="status">
      <span className="sr-only">Loading candidates…</span>
      <div aria-hidden="true">
        <TableShell withMatch={withMatch}>
          {Array.from({ length: SKELETON_ROWS }, (_, row) => (
            <tr key={row}>
              {columnsFor(withMatch).map((column) => (
                <td key={column} className={cell}>
                  <div className="h-3 w-3/4 rounded-sm bg-surface-muted" />
                </td>
              ))}
            </tr>
          ))}
        </TableShell>
      </div>
    </div>
  )
}

export function CandidateTable({ candidates, onDelete, matches, caption }: CandidateTableProps) {
  return (
    <TableShell withMatch={matches !== undefined} caption={caption}>
      {candidates.map((c) => (
        <tr key={c.id} className="transition-colors hover:bg-surface-muted">
          <td className={cell}>
            <Link to={`/admin/candidates/${c.id}`} className="rounded-xs font-medium text-accent-fg underline-offset-4 hover:underline">
              {c.full_name}
            </Link>
          </td>
          {matches && <td className={`${cell} text-fg`}><MatchCell match={matches.get(c.id)} /></td>}
          <td className={`${cell} num text-data text-fg-muted`}>{c.email}</td>
          <td className={`${cell} min-w-48 text-fg-muted`}>{c.headline}</td>
          <td className={`${cell} whitespace-nowrap text-fg-muted`}>
            {c.city}, <span className="num text-data">{c.country_code}</span>
          </td>
          <td className={`${cell} num text-right text-data text-fg`}>{formatYears(c.years_experience)}</td>
          <td className={`${cell} num whitespace-nowrap text-right text-data text-fg-muted`}>
            {c.expected_salary === null || c.salary_currency === null ? '—' : formatSalary(c.expected_salary, c.salary_currency)}
          </td>
          <td className={cell}>
            <div className="flex flex-wrap gap-1">
              {c.top_skills.map((skill) => (
                <Stamp key={skill}>{skill}</Stamp>
              ))}
            </div>
          </td>
          <td className={cell}>
            <Stamp>{c.source}</Stamp>
          </td>
          <td className={`${cell} num whitespace-nowrap text-data text-fg-muted`}>{dateFormat.format(new Date(c.created_at))}</td>
          <td className={`${cell} whitespace-nowrap`}>
            <div className="flex gap-4">
              <Link
                to={`/admin/candidates/${c.id}?edit=1`}
                className="rounded-xs font-medium text-accent-fg underline-offset-4 hover:underline"
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
          </td>
        </tr>
      ))}
    </TableShell>
  )
}
