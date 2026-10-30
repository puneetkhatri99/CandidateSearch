import { formatCount, formatUsd } from '../format'
import type { UsageTotals } from '../types'

interface TotalsTableProps {
  caption: string
  keyLabel: string
  rows: UsageTotals[]
}

const head = 'caps px-3 py-3'

export function TotalsTable({ caption, keyLabel, rows }: TotalsTableProps) {
  return (
    <div className="min-w-0 overflow-x-auto">
      <table className="min-w-full text-left">
        <caption className="pb-3 text-left text-xl font-semibold text-fg">{caption}</caption>
        <thead className="border-b border-border text-fg-muted">
          <tr>
            <th scope="col" className={head}>
              {keyLabel}
            </th>
            <th scope="col" className={`${head} text-right`}>
              Requests
            </th>
            <th scope="col" className={`${head} text-right`}>
              Tokens
            </th>
            <th scope="col" className={`${head} text-right`}>
              Cost
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.length === 0 ? (
            <tr>
              <td colSpan={4} className="px-3 py-4 text-fg-subtle">
                No spending yet.
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={row.key} className="transition-colors hover:bg-surface-muted">
                <td className="num px-3 py-3.5 text-data text-fg">{row.key}</td>
                <td className="num px-3 py-3.5 text-right text-data">{formatCount(row.requests)}</td>
                <td className="num px-3 py-3.5 text-right text-data">{formatCount(row.input_tokens + row.output_tokens)}</td>
                <td className="num px-3 py-3.5 text-right text-data">{formatUsd(row.cost_usd)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
