import { type FormEvent, useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router'
import { ApiError } from '@/shared/api/client'
import { Alert, Button, TextInput } from '@/shared/ui'
import { useCurrentUser, useLogin } from '../hooks'
import { safeNextPath } from '../navigation'

export function LoginPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const next = safeNextPath(params.get('next'))
  const { data: user } = useCurrentUser()
  const loginMutation = useLogin()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  if (user) return <Navigate to={next} replace />

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    try {
      await loginMutation.mutateAsync({ email, password })
      navigate(next, { replace: true })
    } catch (err) {
      setError(
        err instanceof ApiError && [401, 422, 429].includes(err.status)
          ? err.status === 422
            ? 'Enter a valid email and password.'
            : err.message
          : 'Could not sign in. Please try again.',
      )
    }
  }

  return (
    <section className="max-w-sm">
      <h1 className="font-display text-2xl font-semibold tracking-tight text-fg">Staff sign in</h1>
      <form onSubmit={onSubmit} className="mt-6 grid gap-5 border-t border-border pt-6">
        <TextInput
          label="Email"
          type="email"
          autoComplete="username"
          className="num"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <TextInput
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <Alert>{error}</Alert>}
        <Button type="submit" disabled={loginMutation.isPending || !email || !password}>
          {loginMutation.isPending ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </section>
  )
}
