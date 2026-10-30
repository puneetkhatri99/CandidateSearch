/** Mirrors backend/app/features/ai_usage/schemas.py. Decimals arrive as strings. */

export interface UsageTotals {
  key: string
  requests: number
  input_tokens: number
  output_tokens: number
  cost_usd: string
}

export interface BudgetSummary {
  limit_usd: string
  spent_usd: string
  remaining_usd: string
  percent_used: number
  /** Spend has reached the limit: every paid AI call is refused until an admin raises it. */
  limit_reached: boolean
  updated_at: string | null
  by_model: UsageTotals[]
  by_operation: UsageTotals[]
}

export const EVENT_STATUSES = ['succeeded', 'failed', 'blocked'] as const
export type EventStatus = (typeof EVENT_STATUSES)[number]

export interface UsageEvent {
  id: string
  created_at: string
  provider: string
  model: string
  operation: string
  trigger: string
  item_count: number
  input_tokens: number
  output_tokens: number
  cost_usd: string
  status: EventStatus
  error: string | null
}

export interface UsageEventPage {
  items: UsageEvent[]
  next_cursor: string | null
}

/** Filters as strings, exactly as they live in the URL; '' means "not set". */
export interface EventFilters {
  model: string
  operation: string
  status: string
}

export const FILTER_KEYS = ['model', 'operation', 'status'] as const