import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { Alert, PageHeader } from '@/shared/ui'
import { type SystemState, useSystemDetails, useSystemStatus } from '../hooks/useSystemStatus'
import type { EmbeddingHealth } from '../types'

// The row is already labelled "API", so the sidebar's "API online" would repeat it.
const API_WORDS: Record<SystemState, string> = {
  checking: 'Checking…',
  online: 'Online',
  degraded: 'Up, but a dependency below is down',
  offline: 'Offline',
}
const count = (value: number) => value.toLocaleString('en-US')
const usd = (value: string) => `$${Number(value).toFixed(2)}`

function Dot({ ok }: { ok: boolean | undefined }) {
  const tone = ok === undefined ? 'bg-fg-subtle' : ok ? 'bg-success' : 'bg-danger-meter'
  return <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${tone}`} />
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid max-w-3xl gap-3">
      <h2 className="text-xl font-semibold text-fg">{title}</h2>
      <dl className="divide-y divide-border border-y border-border">{children}</dl>
    </section>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-4">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="num flex items-center gap-2 text-fg">{children}</dd>
    </div>
  )
}

function Check({ ok, label }: { ok: boolean | undefined; label: string }) {
  return (
    <>
      <Dot ok={ok} />
      {ok === undefined ? 'Not known' : ok ? 'Online' : `${label} unavailable`}
    </>
  )
}

function Coverage({ health, noun }: { health: EmbeddingHealth; noun: string }) {
  return (
    <>
      <Dot ok={health.current === health.total && health.failed === 0} />
      {count(health.current)} of {count(health.total)} {noun} up to date
      {health.failed > 0 && <span className="text-danger-fg">, {count(health.failed)} failed</span>}
    </>
  )
}

/** The API's live status, then what the AI search runs on and how complete it is. */
export function SystemPage() {
  const status = useSystemStatus()
  const details = useSystemDetails()
  const offline = status.state === 'offline'

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-10">
      <PageHeader title="System" description="Checked every 30 seconds while this page is open." />

      <Section title="Status">
        <Row label="API">
          <Dot ok={status.state === 'checking' ? undefined : !offline} />
          {API_WORDS[status.state]}
        </Row>
        <Row label="Database">
          <Check ok={offline ? undefined : status.checks.database} label="Database" />
        </Row>
        <Row label="pgvector">
          <Check ok={offline ? undefined : status.checks.pgvector} label="pgvector" />
        </Row>
        <Row label="Last checked">{status.checkedAt ? status.checkedAt.toLocaleTimeString() : 'Checking…'}</Row>
      </Section>

      {details.isError ? (
        <Alert>Could not load the search details. The status above still updates.</Alert>
      ) : details.isPending ? (
        <p role="status" className="text-fg-muted">
          Loading search details…
        </p>
      ) : (
        <>
          <Section title="Search and embeddings">
            <Row label="Candidates">
              <Coverage health={details.data.candidates} noun="candidates" />
            </Row>
            <Row label="Jobs">
              <Coverage health={details.data.jobs} noun="jobs" />
            </Row>
            <Row label="AI budget">
              <Dot ok={!details.data.budget.limit_reached} />
              <span>
                {usd(details.data.budget.spent_usd)} of {usd(details.data.budget.limit_usd)} used
                {details.data.budget.limit_reached && ', limit reached'} ·{' '}
                <Link to="/admin/ai-usage" className="rounded-xs text-accent-fg underline-offset-4 hover:underline">
                  AI spending
                </Link>
              </span>
            </Row>
          </Section>
          <Section title="AI models">
            <Row label="Embeddings">{details.data.models.embedding_model}</Row>
            <Row label="Ranking">
              {details.data.models.ranking_model}, prompt {details.data.models.ranking_prompt_version}
            </Row>
            <Row label="Reading the search">
              {details.data.models.ranking_model}, prompt {details.data.models.understanding_prompt_version}
            </Row>
          </Section>
        </>
      )}
    </div>
  )
}
