export type BudgetTone = 'ok' | 'warning' | 'danger'

export const WARNING_PERCENT = 80
const DANGER_PERCENT = 100
const MIN_VISIBLE_USD = 0.0001

/** Embedding calls cost fractions of a cent, so small amounts keep up to 4 decimals ($0.0123). */
export function formatUsd(value: string | number): string {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  if (amount > 0 && amount < MIN_VISIBLE_USD) return `<$${MIN_VISIBLE_USD}`
  if (amount >= 1 || amount === 0) return `$${amount.toFixed(2)}`
  return `$${amount.toFixed(4).replace(/0{1,2}$/, '')}`
}

export function budgetTone(percentUsed: number, limitReached: boolean): BudgetTone {
  if (limitReached || percentUsed >= DANGER_PERCENT) return 'danger'
  if (percentUsed >= WARNING_PERCENT) return 'warning'
  return 'ok'
}

export const formatCount = (value: number) => value.toLocaleString('en-US')