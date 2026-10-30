import { Link, Outlet, useLocation } from 'react-router'
import { UserMenu, useCurrentUser } from '@/features/auth'
import { SystemStatus } from '@/features/system-status'

function Wordmark() {
  return (
    <span className="font-display text-xl font-semibold leading-none tracking-tight text-fg">
      candidate<span className="text-accent-fg">Search</span>
    </span>
  )
}

function SkipLink() {
  return (
    <a
      href="#main"
      className="sr-only rounded-sm bg-accent px-3 py-2 text-sm font-medium text-on-accent focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50"
    >
      Skip to content
    </a>
  )
}

const navLinkClass = (active: boolean) =>
  `block border-b-2 px-3 py-2 text-sm font-medium transition-colors md:border-b-0 md:border-l-2 md:py-2.5 ${
    active
      ? 'border-accent bg-surface-muted text-fg'
      : 'border-transparent text-fg-muted hover:bg-surface-muted/60 hover:text-fg'
  }`

/** Staff shell: fixed left sidebar on desktop, a top bar at phone width. */
export function RootLayout() {
  const { pathname } = useLocation()
  const { data: user } = useCurrentUser()
  const onCreate = pathname === '/admin/candidates/new'
  const onCreateJob = pathname === '/jobs/new'
  const links = [
    { to: '/admin/candidates', label: 'Candidates', active: pathname.startsWith('/admin/candidates') && !onCreate },
    { to: '/admin/candidates/new', label: 'Add candidate', active: onCreate },
    { to: '/jobs', label: 'Jobs', active: pathname.startsWith('/jobs') && !onCreateJob },
    { to: '/jobs/new', label: 'Add job', active: onCreateJob },
    { to: '/admin/ai-usage', label: 'AI spending', active: pathname.startsWith('/admin/ai-usage') },
    ...(user?.role === 'admin' ? [{ to: '/admin/users', label: 'Users', active: pathname.startsWith('/admin/users') }] : []),
  ]

  return (
    <div className="min-h-screen bg-surface text-fg md:pl-60">
      <SkipLink />
      <aside className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border bg-surface-raised px-4 pt-3 md:fixed md:inset-y-0 md:left-0 md:w-60 md:flex-col md:items-stretch md:justify-start md:gap-8 md:overflow-y-auto md:border-b-0 md:border-r md:px-5 md:py-6">
        <Link to="/admin/candidates" className="order-1 rounded-xs">
          <Wordmark />
        </Link>
        <nav aria-label="Main" className="order-3 -mx-4 w-[calc(100%+2rem)] overflow-x-auto px-4 md:order-2 md:mx-0 md:w-auto md:overflow-visible md:px-0">
          <ul className="flex md:flex-col">
            {links.map((link) => (
              <li key={link.to} className="shrink-0">
                <Link to={link.to} aria-current={link.active ? 'page' : undefined} className={navLinkClass(link.active)}>
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="order-2 flex flex-col gap-3 md:order-3 md:mt-auto md:border-t md:border-border md:pt-4">
          <UserMenu stacked />
          <div className="hidden md:block">
            <SystemStatus />
          </div>
        </div>
      </aside>
      <main id="main" className="min-w-0 px-4 py-6 md:px-10 md:py-8">
        <Outlet />
      </main>
    </div>
  )
}

/** Public shell for the candidate form, privacy notice and login: one focused column, no sidebar. */
export function PublicLayout() {
  const { data: user } = useCurrentUser()
  return (
    <div className="flex min-h-screen flex-col border-t-2 border-accent bg-surface text-fg">
      <SkipLink />
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 px-5 py-4">
          <Link to="/" className="rounded-xs">
            <Wordmark />
          </Link>
          <nav aria-label="Main" className="flex gap-1">
            <Link to="/apply" className="rounded-sm px-3 py-1.5 text-sm font-medium text-fg-muted hover:bg-surface-muted hover:text-fg">
              Apply
            </Link>
            {user && !user.must_change_password && (
              <Link to="/admin/candidates" className="rounded-sm px-3 py-1.5 text-sm font-medium text-fg-muted hover:bg-surface-muted hover:text-fg">
                Candidates
              </Link>
            )}
          </nav>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-3xl flex-1 px-5 py-10">
        <Outlet />
      </main>
      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 px-5 py-4">
          <SystemStatus />
          <UserMenu />
        </div>
      </footer>
    </div>
  )
}
