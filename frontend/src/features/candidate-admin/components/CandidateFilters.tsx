import { COUNTRIES } from '@/shared/data/countries'
import { Button, SelectInput, TextInput } from '@/shared/ui'
import { FILTER_LABELS, type SearchFilters } from '../types'

const SOURCES = [
  { value: 'manual', label: 'Candidate form' },
  { value: 'admin', label: 'Added by staff' },
  { value: 'synthetic', label: 'Synthetic (dev)' },
]

interface CandidateFiltersProps {
  filters: SearchFilters
  onChange: (key: keyof SearchFilters, value: string) => void
  onClear: () => void
}

export function CandidateFilters({ filters, onChange, onClear }: CandidateFiltersProps) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
      <TextInput
        label={FILTER_LABELS.min_years}
        inputMode="decimal"
        className="num"
        value={filters.min_years}
        onChange={(e) => onChange('min_years', e.target.value)}
      />
      <TextInput
        label={FILTER_LABELS.skill}
        placeholder="e.g. python, fastapi"
        value={filters.skill}
        onChange={(e) => onChange('skill', e.target.value)}
      />
      <TextInput
        label={FILTER_LABELS.city}
        placeholder="e.g. Pune"
        value={filters.city}
        onChange={(e) => onChange('city', e.target.value)}
      />
      <SelectInput label={FILTER_LABELS.country} value={filters.country} onChange={(e) => onChange('country', e.target.value)}>
        <option value="">Any country</option>
        {COUNTRIES.map((c) => (
          <option key={c.code} value={c.code}>
            {c.name}
          </option>
        ))}
      </SelectInput>
      <SelectInput label={FILTER_LABELS.source} value={filters.source} onChange={(e) => onChange('source', e.target.value)}>
        <option value="">Any source</option>
        {SOURCES.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </SelectInput>
      <div className="flex items-end">
        <Button variant="secondary" onClick={onClear}>
          Clear all
        </Button>
      </div>
    </div>
  )
}
