// BD Manager's pipeline board: every property by stage, best-rated first, so "what needs me?" is
// one glance. Moves happen on the review page (each needs a reason), not by dragging.
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { fmt } from '../../components/ScoreBreakdown'
import { OUTCOME_RANK, OutcomeBadge } from '../scouting/shared'

const COLUMNS = [
  { key: 'scouted', label: 'Scouted', stages: ['scouted'], hint: 'new — not looked at yet' },
  { key: 'under_review', label: 'Under review', stages: ['under_review'] },
  { key: 'needs_follow_up', label: 'Needs follow-up', stages: ['needs_follow_up'], hint: 'waiting on the executive', tone: 'bg-accent/70' },
  { key: 'shortlisted', label: 'Shortlisted', stages: ['shortlisted'] },
  { key: 'study', label: 'In study', stages: ['study_requested', 'study_in_progress', 'study_complete'], hint: 'M3' },
  { key: 'on_hold', label: 'On hold', stages: ['on_hold'] },
  { key: 'approved', label: 'Approved', stages: ['approved'], tone: 'bg-emerald-100' },
  { key: 'rejected', label: 'Rejected', stages: ['rejected'], tone: 'bg-stone-200' },
]
const OUTCOMES = ['Strong Fit', 'Consider', 'Needs Info', 'Weak Fit']
const byRating = (a, b) => (OUTCOME_RANK[a.outcome] ?? 9) - (OUTCOME_RANK[b.outcome] ?? 9) || (b.score ?? -1) - (a.score ?? -1)

function PropertyCard({ p }) {
  const missing = p.missing_fields.filter((f) => f !== 'photos')
  return (
    <Link to={`/properties/${p.id}`} className="block rounded-md border border-brand/15 bg-white p-2.5 text-sm shadow-sm hover:border-brand/50">
      <div className="flex items-start gap-2">
        <span className="font-semibold leading-tight">{p.label}</span>
        {p.score != null && <span className="ml-auto tabular-nums">{fmt(p.score, 0)}</span>}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1">
        {p.outcome ? <OutcomeBadge outcome={p.outcome} /> : <span className="text-xs opacity-60">{p.evaluation_status === 'pending' ? 'evaluating…' : 'not evaluated'}</span>}
        {p.stage.startsWith('study_') && <span className="text-xs opacity-70">{p.stage.replace('study_', '').replace('_', ' ')}</span>}
      </div>
      <div className="mt-1 text-xs opacity-70">#{p.id} · {p.locality ?? p.pincode ?? '—'}</div>
      {(p.status === 'possible_duplicate' || missing.length > 0 || p.missing_fields.includes('photos')) && (
        <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
          {p.status === 'possible_duplicate' && <span className="rounded bg-amber-100 px-1 text-amber-900">possible duplicate</span>}
          {missing.length > 0 && <span className="rounded bg-amber-100 px-1 text-amber-900">missing {missing.join(', ').replaceAll('_', ' ')}</span>}
          {p.missing_fields.includes('photos') && <span className="rounded bg-stone-100 px-1">no photos</span>}
        </div>
      )}
    </Link>
  )
}

export default function BoardPage() {
  const list = useQuery({ queryKey: ['properties'], queryFn: () => api('/properties'), refetchInterval: 15000 })
  const [q, setQ] = useState('')
  const [outcome, setOutcome] = useState(null)

  const { columns, merged, shown } = useMemo(() => {
    const all = list.data ?? []
    const needle = q.trim().toLowerCase()
    const live = all.filter((p) => p.status !== 'merged')
    const filtered = live.filter((p) => (!outcome || p.outcome === outcome)
      && (!needle || [p.label, p.locality, p.pincode, String(p.id)].some((v) => v?.toLowerCase().includes(needle))))
    return {
      columns: COLUMNS.map((c) => ({ ...c, items: filtered.filter((p) => c.stages.includes(p.stage)).sort(byRating) })),
      merged: all.length - live.length,
      shown: filtered.length,
    }
  }, [list.data, q, outcome])

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 px-4 pt-4 pb-2">
        <h1 className="mr-2 text-xl font-bold">Pipeline</h1>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, locality, pincode, #id"
               className="w-full rounded border bg-white px-2 py-1.5 text-sm sm:w-64" />
        <div className="flex flex-wrap gap-1">
          {[null, ...OUTCOMES].map((o) => (
            <button key={o ?? 'all'} onClick={() => setOutcome(o)}
                    className={`rounded-full px-2.5 py-1 text-xs ${outcome === o ? 'bg-brand text-white' : 'bg-white ring-1 ring-brand/20'}`}>{o ?? 'All'}</button>
          ))}
        </div>
        <span className="text-xs opacity-60 sm:ml-auto">
          {list.data ? `${shown} properties${merged ? ` · ${merged} merged duplicates hidden` : ''}` : 'Loading…'}
        </span>
      </div>
      {list.isError && <p className="px-4 text-red-700">{list.error.message}</p>}
      <div className="flex min-h-0 flex-1 snap-x gap-3 overflow-x-auto px-4 pb-4">
        {columns.map((c) => (
          <section key={c.key} className="flex w-64 shrink-0 snap-start flex-col rounded-lg bg-white/60 ring-1 ring-brand/10">
            <header className={`rounded-t-lg px-2.5 py-2 ${c.tone ?? 'bg-brand/10'}`}>
              <div className="flex items-center text-sm font-semibold">{c.label}<span className="ml-auto tabular-nums">{c.items.length}</span></div>
              {c.hint && <div className="text-xs opacity-70">{c.hint}</div>}
            </header>
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
              {c.items.map((p) => <PropertyCard key={p.id} p={p} />)}
              {c.items.length === 0 && <p className="p-2 text-center text-xs opacity-50">—</p>}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
