import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { ROLE_LABELS, useAuth } from './auth'

export default function RoleSwitcher({ variant = 'header' }) {
  const { user, switchUser } = useAuth()
  const [error, setError] = useState(null)
  const users = useQuery({ queryKey: ['demo-users'], queryFn: () => api('/auth/demo-users', { token: '' }) })

  const choose = async (id) => {
    setError(null)
    try {
      await switchUser(Number(id))
    } catch (e) {
      setError(e.message)
    }
  }

  if (variant === 'cards') {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {users.data?.map((u) => (
          <button
            key={u.id}
            onClick={() => choose(u.id)}
            className="rounded-lg border border-brand/20 bg-white p-4 text-left shadow-sm transition hover:border-brand hover:shadow"
          >
            <div className="font-semibold text-ink">{u.name.replace(/ \(.*\)$/, '')}</div>
            <div className="text-sm text-brand">{ROLE_LABELS[u.role]}</div>
          </button>
        ))}
        {users.isError && <p className="text-sm text-red-700">Can't reach the API: {users.error.message}</p>}
        {error && <p className="text-sm text-red-700">{error}</p>}
      </div>
    )
  }

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="hidden opacity-80 sm:inline">Acting as</span>
      <select
        value={user?.id ?? ''}
        onChange={(e) => choose(e.target.value)}
        className="rounded-md border border-white/30 bg-brand-dark px-2 py-1 text-white focus:outline-none focus:ring-2 focus:ring-accent"
        aria-label="Switch demo user"
      >
        {users.data?.map((u) => (
          <option key={u.id} value={u.id}>
            {u.name}
          </option>
        ))}
      </select>
    </label>
  )
}
