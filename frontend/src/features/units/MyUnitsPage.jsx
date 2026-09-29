// Survey Executive home (docs/DESIGN.md §4): "my units today". Only units assigned to me on studies
// in progress; the property is just a label.
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { useAuth } from '../../app/auth'
import { fmt } from '../../components/ScoreBreakdown'

export default function MyUnitsPage() {
  const { user } = useAuth()
  const mine = useQuery({ queryKey: ['my-units'], queryFn: () => api('/my/units'), refetchInterval: 30000 })
  const units = mine.data ?? []
  const todo = units.filter((u) => u.surveyed + u.gaps < u.segment_count)
  const done = units.filter((u) => u.surveyed + u.gaps >= u.segment_count)

  const Row = ({ u }) => (
    <Link to={`/units/${u.id}`} className="block rounded-lg border border-brand/15 bg-white p-3 active:bg-brand-light">
      <div className="flex items-baseline gap-2">
        <span className="text-lg font-bold">{u.label}</span>
        <span className="min-w-0 truncate text-sm">near {u.property.label}</span>
        <span className="ml-auto text-sm tabular-nums whitespace-nowrap">≈ {fmt(u.minutes / 60, 1)} h</span>
      </div>
      <div className="mt-1.5 flex h-1.5 overflow-hidden rounded bg-stone-200">
        <div className="bg-emerald-600" style={{ width: `${(100 * u.surveyed) / u.segment_count}%` }} />
        <div className="bg-amber-500" style={{ width: `${(100 * u.gaps) / u.segment_count}%` }} />
      </div>
      <p className="mt-1 text-xs opacity-70">{u.surveyed + u.gaps} of {u.segment_count} lanes done · {fmt(u.length_m / 1000, 1)} km{u.pieces > 1 && ` in ${u.pieces} parts`}</p>
    </Link>
  )

  return (
    <div className="mx-auto max-w-xl space-y-4 p-4 pb-20">
      <div>
        <p className="text-sm text-brand">Hi {user.name.replace(/ \(.*\)$/, '')}</p>
        <h1 className="text-xl font-bold">My units today</h1>
      </div>
      {mine.isError && <p className="text-red-700">{mine.error.message}</p>}
      {mine.data && units.length === 0 && <p className="text-sm">Nothing assigned right now. The Survey Manager assigns units when a study starts.</p>}
      {todo.length > 0 && <ul className="space-y-2">{todo.map((u) => <li key={u.id}><Row u={u} /></li>)}</ul>}
      {done.length > 0 && (
        <section>
          <h2 className="mb-1 text-sm font-semibold opacity-70">Finished</h2>
          <ul className="space-y-2">{done.map((u) => <li key={u.id}><Row u={u} /></li>)}</ul>
        </section>
      )}
    </div>
  )
}
