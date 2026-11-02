import { Link } from 'react-router'
import { useCurrentUser } from '@/features/auth'
import { PageHeader } from '@/shared/ui'

interface SettingLink {
  to: string
  label: string
  description: string
}

/** Account and admin pages that don't need a place in the main navigation. */
export function SettingsPage() {
  const { data: user } = useCurrentUser()
  const settings: SettingLink[] = [
    {
      to: '/settings/searches',
      label: 'Saved searches',
      description: 'Your past searches and their results; star one to keep it.',
    },
    {
      to: '/account/password?next=%2Fsettings',
      label: 'Change password',
      description: 'Set a new password for your own account.',
    },
    ...(user?.role === 'admin'
      ? [{ to: '/admin/users', label: 'Users', description: 'Add staff, change roles and reset passwords.' }]
      : []),
    { to: '/admin/system', label: 'System', description: 'API status, search health and the AI models in use.' },
  ]

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-8">
      <PageHeader title="Settings" />
      <ul className="max-w-3xl divide-y divide-border border-y border-border">
        {settings.map((setting) => (
          <li key={setting.to} className="py-4">
            <Link
              to={setting.to}
              className="rounded-xs text-base font-semibold text-accent-fg underline-offset-4 hover:underline"
            >
              {setting.label}
            </Link>
            <p className="mt-1 text-sm text-fg-muted">{setting.description}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}
