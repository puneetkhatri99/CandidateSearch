import { Link } from 'react-router'
import { linkButtonClass } from '@/shared/ui'

export function HomePage() {
  return (
    <section>
      <h1 className="font-display text-4xl font-semibold leading-tight tracking-tight">Find your next role</h1>
      <p className="mt-3 max-w-prose text-base text-fg-muted">Create a profile once and get matched with relevant job roles.</p>
      <Link to="/apply" className={`${linkButtonClass('primary')} mt-8`}>
        Create your profile
      </Link>
    </section>
  )
}

export function NotFoundPage() {
  return (
    <section>
      <h1 className="font-display text-2xl font-semibold tracking-tight">Page not found</h1>
      <Link to="/" className="mt-4 inline-block rounded-xs text-accent-fg underline underline-offset-4">
        Go home
      </Link>
    </section>
  )
}
