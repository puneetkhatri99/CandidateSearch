import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { Stamp } from '@/shared/ui'
import { formatSalary, formatYears } from '@/shared/format'
import type { CandidateSummary } from '../types'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

const COLUMNS = ['Name', 'Email', 'Headline', 'Location', 'Years', 'Expected pay', 'Top skills', 'Source', 'Added', 'Actions']
const SKELETON_ROWS = 6
const cell = 'px-3 py-4 align-top'
const RIGHT_ALIGNED = new Set(['Years', 'Expected pay'])

interface CandidateTableProps {
  candidates: CandidateSummary[]
  /** Omitted for users who may not delete; the Delete action is then hidden. */
  onDelete?: (candidate: CandidateSummary) => void
}

function TableShell({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left">
        <caption className="sr-only">Candidates matching your search</caption>
        <thead className="border-b border-border text-fg-muted">
          <tr>
            {COLUMNS.map((column) => (
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

export function CandidateTableSkeleton() {
  return (
    <div role="status">
      <span className="sr-only">Loading candidates…</span>
      <div aria-hidden="true">
        <TableShell>
          {Array.from({ length: SKELETON_ROWS }, (_, row) => (
            <tr key={row}>
              {COLUMNS.map((column) => (
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

export function CandidateTable({ candidates, onDelete }: CandidateTableProps) {
  return (
    <TableShell>
      {candidates.map((c) => (
        <tr key={c.id} className="transition-colors hover:bg-surface-muted">
          <td className={cell}>
            <Link to={`/admin/candidates/${c.id}`} className="rounded-xs font-medium text-accent-fg underline-offset-4 hover:underline">
              {c.full_name}
            </Link>
          </td>
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
