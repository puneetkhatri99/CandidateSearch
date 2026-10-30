export interface HealthStatus {
  status: 'ok' | 'unavailable'
  checks: Record<string, boolean>
}
