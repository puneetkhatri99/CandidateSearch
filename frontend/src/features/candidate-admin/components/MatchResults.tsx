import type { CandidateSummary, SemanticSearchResult } from '../types'
import { MatchCard } from './MatchCard'

interface MatchResultsProps {
  result: SemanticSearchResult
  /** Hard filters were applied, so the results come as "Perfect matches" and "Filtered out". */
  filtered: boolean
  onDelete?: (candidate: CandidateSummary) => void
}

/** AI-ranked candidates: those passing every hard filter, then the ones a filter removed. */
export function MatchResults({ result, filtered, onDelete }: MatchResultsProps) {
  const ranked = result.ranked_by === 'ai'

  return (
    <div className="grid gap-8 motion-safe:animate-reveal">
      <section className="grid gap-3">
        {filtered && <h2 className="font-semibold text-fg">Perfect matches</h2>}
        {result.items.length > 0 ? (
          <ol
            aria-label={filtered ? 'Candidates matching every filter' : 'Candidates matching your search'}
            className="divide-y divide-border border-y border-border"
          >
            {result.items.map((match, index) => (
              <MatchCard key={match.candidate.id} match={match} rank={ranked ? index + 1 : undefined} onDelete={onDelete} />
            ))}
          </ol>
        ) : (
          <p className="text-fg-muted">No top result matches every filter. The closest ones are below.</p>
        )}
      </section>
      {result.filtered_out.length > 0 && (
        <section className="grid gap-3">
          <h2 className="font-semibold text-fg">Filtered out</h2>
          <p className="text-sm text-fg-muted">Good matches that miss a filter, in the same ranked order.</p>
          <ol aria-label="Search matches removed by a filter" className="divide-y divide-border border-y border-border">
            {result.filtered_out.map((match) => (
              <MatchCard key={match.candidate.id} match={match} onDelete={onDelete} />
            ))}
          </ol>
        </section>
      )}
    </div>
  )
}
