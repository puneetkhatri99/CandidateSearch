import { useMemo } from 'react'
import type { CandidateSummary, SemanticSearchResult } from '../types'
import { CandidateTable } from './CandidateTable'

interface MatchResultsProps {
  result: SemanticSearchResult
  /** Hard filters were applied, so the results come as "Perfect matches" and "Filtered out". */
  filtered: boolean
  fetching?: boolean
  onDelete?: (candidate: CandidateSummary) => void
}

/** AI-ranked candidates: those passing every hard filter, then the ones a filter removed. */
export function MatchResults({ result, filtered, fetching = false, onDelete }: MatchResultsProps) {
  const matches = useMemo(
    () => new Map([...result.items, ...result.filtered_out].map((m) => [m.candidate.id, m])),
    [result],
  )
  const perfect = result.items.map((m) => m.candidate)
  const filteredOut = result.filtered_out.map((m) => m.candidate)

  return (
    <div className={`grid gap-8 ${fetching ? 'opacity-60 transition-opacity' : ''}`}>
      <section className="grid gap-3">
        {filtered && <h2 className="font-semibold text-fg">Perfect matches</h2>}
        {perfect.length > 0 ? (
          <CandidateTable
            candidates={perfect}
            onDelete={onDelete}
            matches={matches}
            caption={filtered ? 'Candidates matching every filter' : undefined}
          />
        ) : (
          <p className="text-fg-muted">No top result matches every filter. The closest ones are below.</p>
        )}
      </section>
      {filteredOut.length > 0 && (
        <section className="grid gap-3">
          <h2 className="font-semibold text-fg">Filtered out</h2>
          <p className="text-sm text-fg-muted">Good matches that miss a filter, in the same ranked order.</p>
          <CandidateTable
            candidates={filteredOut}
            onDelete={onDelete}
            matches={matches}
            caption="Search matches removed by a filter"
          />
        </section>
      )}
    </div>
  )
}
