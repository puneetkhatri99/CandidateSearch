export interface HealthStatus {
  status: 'ok' | 'unavailable'
  checks: Record<string, boolean>
}

export interface EmbeddingHealth {
  total: number
  current: number
  failed: number
}

/** Mirrors backend health.schemas.SystemDetails: counts, model names and money only. */
export interface SystemDetails {
  models: {
    embedding_model: string
    ranking_model: string
    ranking_prompt_version: string
    understanding_prompt_version: string
  }
  candidates: EmbeddingHealth
  jobs: EmbeddingHealth
  budget: { spent_usd: string; limit_usd: string; limit_reached: boolean }
}
