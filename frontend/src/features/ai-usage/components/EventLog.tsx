import type { ReactNode } from 'react'
import { Stamp, type StampTone } from '@/shared/ui'
import { formatCount, formatUsd } from '../format'
import type { EventStatus, UsageEvent } from '../types'

const dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

const COLUMNS = ['Time', 'Model', 'Operation', 'Trigger', 'Items', 'Tokens', 'Cost', 'Status']
const RIGHT_ALIGNED = ['Items', 'Tokens', 'Cost']
const SKELETON_ROWS = 5
const cell = 'px-3 py-3.5'

const STATUS_TONES: Record<EventStatus, StampTone> = {
  succeeded: 'success',
  failed: 'danger',
  blocked: 'dangerSolid',
}

function TableShell({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left">
        <caption className="sr-only">AI request log, newest first</caption>
        <thead className="border-b border-border text-fg-muted">
          <tr>
            {COLUMNS.map((column) => (
              <th key={column} scope="col" className={`caps whitespace-nowrap px-3 py-3 ${RIGHT_ALIGNED.includes(column) ? 'text-right' : ''}`}>
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

export function EventLogSkeleton() {
  return (
    <div role="status">
      <span className="sr-only">Loading requests…</span>
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

export function EventLog({ events }: { events: UsageEvent[] }) {
  return (
    <TableShell>
      {events.map((event) => (
        <tr
          key={event.id}
          className={`transition-colors ${event.status === 'blocked' ? 'bg-danger-soft' : 'hover:bg-surface-muted'}`}
          data-status={event.status}
        >
          <td className={`${cell} num whitespace-nowrap text-data text-fg-muted`}>{dateTimeFormat.format(new Date(event.created_at))}</td>
          <td className={`${cell} num text-data text-fg`}>{event.model}</td>
          <td className={`${cell} num text-data text-fg-muted`}>{event.operation}</td>
          <td className={`${cell} num text-data text-fg-muted`}>{event.trigger}</td>
          <td className={`${cell} num text-right text-data`}>{formatCount(event.item_count)}</td>
          <td className={`${cell} num text-right text-data`}>{formatCount(event.input_tokens + event.output_tokens)}</td>
          <td className={`${cell} num text-right text-data`}>{formatUsd(event.cost_usd)}</td>
          <td className={cell}>
            <Stamp tone={STATUS_TONES[event.status]}>{event.status}</Stamp>
          </td>
        </tr>
      ))}
    </TableShell>
  )
}
