import type { BudgetSummary, UsageEvent } from './types'

export const budgetSummary = (overrides: Partial<BudgetSummary> = {}): BudgetSummary => ({
  limit_usd: '5.00',
  spent_usd: '0.012300',
  remaining_usd: '4.987700',
  percent_used: 0.246,
  limit_reached: false,
  updated_at: null,
  by_model: [{ key: 'text-embedding-3-small', requests: 2, input_tokens: 600000, output_tokens: 0, cost_usd: '0.012300' }],
  by_operation: [{ key: 'candidate_embedding', requests: 2, input_tokens: 600000, output_tokens: 0, cost_usd: '0.012300' }],
  ...overrides,
})

export const usageEvent = (overrides: Partial<UsageEvent> = {}): UsageEvent => ({
  id: 'e-1',
  created_at: '2026-10-29T10:00:00Z',
  provider: 'openai',
  model: 'text-embedding-3-small',
  operation: 'candidate_embedding',
  trigger: 'worker',
  item_count: 8,
  input_tokens: 3200,
  output_tokens: 0,
  cost_usd: '0.000064',
  status: 'succeeded',
  error: null,
  ...overrides,
})