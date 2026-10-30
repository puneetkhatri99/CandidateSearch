import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { budgetSummary } from '../testing'
import { BudgetCard } from './BudgetCard'

const tone = () => screen.getByRole('progressbar').getAttribute('data-tone')

describe('BudgetCard', () => {
  it('shows spent of limit and remaining with enough decimals', () => {
    render(<BudgetCard summary={budgetSummary()} />)

    expect(screen.getByText(/\$0\.0123/)).toBeInTheDocument()
    expect(screen.getByText(/of \$5\.00/)).toBeInTheDocument()
    expect(screen.getByText('$4.99')).toBeInTheDocument()
    expect(screen.queryByText(/Pending/)).not.toBeInTheDocument()
  })

  it('is green under 80%', () => {
    render(<BudgetCard summary={budgetSummary({ percent_used: 79 })} />)
    expect(tone()).toBe('ok')
  })

  it('turns amber at 80%', () => {
    render(<BudgetCard summary={budgetSummary({ percent_used: 80 })} />)
    expect(tone()).toBe('warning')
  })

  it('turns red at 100% and caps the bar width', () => {
    render(<BudgetCard summary={budgetSummary({ percent_used: 130 })} />)
    expect(tone()).toBe('danger')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
  })

  it('turns red and explains when the limit is reached', () => {
    render(<BudgetCard summary={budgetSummary({ percent_used: 100, limit_reached: true })} />)
    expect(tone()).toBe('danger')
    expect(screen.getByText('Limit reached')).toBeInTheDocument()
    expect(screen.getByText(/AI requests are paused/)).toBeInTheDocument()
  })

  it('says nothing about pausing below the limit', () => {
    render(<BudgetCard summary={budgetSummary({ percent_used: 90 })} />)
    expect(screen.queryByText(/AI requests are paused/)).not.toBeInTheDocument()
  })

  it('shows Edit limit only when an edit handler is provided', () => {
    const { rerender } = render(<BudgetCard summary={budgetSummary()} />)
    expect(screen.queryByRole('button', { name: 'Edit limit' })).not.toBeInTheDocument()

    rerender(<BudgetCard summary={budgetSummary()} onEdit={() => undefined} />)
    expect(screen.getByRole('button', { name: 'Edit limit' })).toBeInTheDocument()
  })
})