/** Years of experience always show one decimal and at least two integer digits ("06.5"). */
export const formatYears = (years: number): string => years.toFixed(1).padStart(4, '0')

/** A yearly amount with its currency, e.g. "₹1,800,000" or "€90,000". */
export const formatSalary = (amount: number, currency: string): string =>
  new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 0 }).format(amount)

/** A job's pay range: "€60,000 – €90,000", "up to €90,000", "from €60,000", or null if none. */
export function formatPayRange(min: number | null, max: number | null, currency: string | null): string | null {
  if (currency === null || (min === null && max === null)) return null
  if (min !== null && max !== null) return `${formatSalary(min, currency)} – ${formatSalary(max, currency)}`
  return max !== null ? `up to ${formatSalary(max, currency)}` : `from ${formatSalary(min ?? 0, currency)}`
}
