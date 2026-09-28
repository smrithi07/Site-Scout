// Survey Manager home (docs/DESIGN.md §4): the study request inbox. New requests (awaiting a
// reuse decision) first, then planned and in-progress studies; finished ones folded away.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { useAuth } from '../../app/auth'
import { fmt } from '../../components/ScoreBreakdown'
import { MODES, StatusBadge } from './reuse'

const GROUPS = [
  { key: 'requested', title: 'Needs your plan', hint: 'decide what to reuse and what to survey' },
  { key: 'planned', title: 'Planned — assign units' },
  { key: 'in_progress', title: 'Surveying' },
]
const when = (at) => new Date(at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })

function StudyRow({ s }) {
  return (
    <Link to={`/studies/${s.id}`} className="block rounded-lg border border-brand/15 bg-white p-3 hover:border-brand/50">
      <div className="flex items-start gap-2">
        <div className="min-w-0">
          <p className="font-semibold">{s.property.label}</p>
          <p className="text-xs opacity-70">#{s.id} · {s.property.locality ?? '—'} · requested {when(s.created_at)}</p>
        </div>
        <span className="ml-auto"><StatusBadge status={s.status} /></span>
      </div>
      <p className="mt-1.5 text-sm">{s.reuse.message}</p>
      <p className="mt-0.5 text-xs opacity-70">
        BD asked: {MODES[s.requested_mode].label}{s.request_reason && ` — “${s.request_reason}”`}
        {s.status !== 'requested' && ` · ${s.survey.segments} lanes (${fmt(s.survey.length_m / 1000, 1)} km) · ${s.units.count} units, ${s.units.assigned} assigned`}
      </p>
    </Link>
  )
}

export default function InboxPage() {
  const { user } = useAuth()
  const list = useQuery({ queryKey: ['studies'], queryFn: () => api('/studies'), refetchInterval: 20000 })
  const [showDone, setShowDone] = useState(false)
  const all = list.data ?? []
  const done = all.filter((s) => ['complete', 'cancelled'].includes(s.status))

  return (
    <div className="mx-auto max-w-2xl space-y-5 p-4">
      <div>
        <p className="text-sm text-brand">Hi {user.name.replace(/ \(.*\)$/, '')}</p>
        <h1 className="text-xl font-bold">Catchment studies</h1>
      </div>
      {list.isError && <p className="text-red-700">{list.error.message}</p>}
      {list.data && all.length === 0 && <p className="text-sm">No study requests yet. They appear here when the BD Manager requests one on a shortlisted property.</p>}
      {GROUPS.map((g) => {
        const items = all.filter((s) => s.status === g.key)
        if (!items.length) return null
        return (
          <section key={g.key}>
            <h2 className="mb-1 text-sm font-semibold">{g.title} <span className="opacity-60">({items.length})</span>
              {g.hint && <span className="ml-1 font-normal opacity-60">— {g.hint}</span>}</h2>
            <ul className="space-y-2">{items.map((s) => <li key={s.id}><StudyRow s={s} /></li>)}</ul>
          </section>
        )
      })}
      {done.length > 0 && (
        <section>
          <button onClick={() => setShowDone((v) => !v)} className="text-sm text-brand underline">
            {showDone ? 'Hide' : 'Show'} finished and cancelled ({done.length})
          </button>
          {showDone && <ul className="mt-2 space-y-2">{done.map((s) => <li key={s.id}><StudyRow s={s} /></li>)}</ul>}
        </section>
      )}
    </div>
  )
}
