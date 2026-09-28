// BD Executive home (docs/DESIGN.md §4): my scouting tasks, what the manager is waiting on, unsent
// drafts, and a prominent "Add property".
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { useAuth } from '../../app/auth'
import { listDrafts } from './drafts'

const STATUS_STYLE = { open: 'bg-accent text-ink', in_progress: 'bg-brand/15 text-brand', done: 'bg-emerald-100 text-emerald-900',
                       cancelled: 'bg-stone-200 text-stone-700' }

export default function ExecHome() {
  const { user } = useAuth()
  const tasks = useQuery({ queryKey: ['tasks'], queryFn: () => api('/tasks') })
  const followUps = useQuery({ queryKey: ['follow-ups'], queryFn: () => api('/follow-ups') })
  const drafts = listDrafts(user.id)
  const active = (tasks.data ?? []).filter((t) => ['open', 'in_progress'].includes(t.status))
  const finished = (tasks.data ?? []).filter((t) => !['open', 'in_progress'].includes(t.status))

  return (
    <div className="mx-auto max-w-xl space-y-5 p-4 pb-24">
      <div>
        <p className="text-sm text-brand">Hi {user.name.replace(/ \(.*\)$/, '')}</p>
        <h1 className="text-xl font-bold">My scouting</h1>
      </div>

      {(followUps.data?.length ?? 0) > 0 && (
        <section>
          <h2 className="mb-1 text-sm font-semibold text-amber-800">The manager is waiting on you</h2>
          <ul className="space-y-2">
            {followUps.data.map((f) => (
              <li key={f.id}>
                <Link to={`/properties/${f.property_id}`} className="block rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
                  <span className="text-xs uppercase opacity-70">{f.kind.replace('_', ' ')}</span> · property #{f.property_id}
                  <div>{f.message}</div>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {drafts.length > 0 && (
        <section>
          <h2 className="mb-1 text-sm font-semibold">Unsent drafts (on this phone)</h2>
          <ul className="space-y-1">
            {drafts.map((d) => (
              <li key={d.clientId}>
                <Link to={`/properties/new?draft=${d.clientId}`} className="block rounded-lg border border-brand/15 bg-white p-3 text-sm">
                  {d.fields.label || 'Untitled property'} <span className="opacity-60">· {new Date(d.updatedAt).toLocaleString('en-IN')}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2 className="mb-1 text-sm font-semibold">Tasks</h2>
        {tasks.isLoading && <p className="text-sm">Loading…</p>}
        {active.length === 0 && !tasks.isLoading && <p className="text-sm opacity-70">No open tasks. You can still add a property you've found.</p>}
        <ul className="space-y-2">
          {[...active, ...finished].map((t) => (
            <li key={t.id}>
              <Link to={`/tasks/${t.id}`} className={`block rounded-lg border border-brand/15 bg-white p-3 ${active.includes(t) ? '' : 'opacity-60'}`}>
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{t.title}</span>
                  <span className={`ml-auto rounded-full px-2 py-0.5 text-xs ${STATUS_STYLE[t.status]}`}>{t.status.replace('_', ' ')}</span>
                </div>
                <div className="mt-0.5 text-xs opacity-70">
                  {t.hotspot_cells.length} hotspot(s) · {t.target_cells.length} map cells{t.due_date && ` · due ${new Date(t.due_date).toLocaleDateString('en-IN')}`}
                </div>
                {t.note && <div className="mt-1 text-sm">{t.note}</div>}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <Link to="/properties/new" className="fixed right-4 bottom-4 left-4 mx-auto block max-w-xl rounded-full bg-accent px-4 py-3 text-center font-semibold text-ink shadow-lg">
        ＋ Add property
      </Link>
    </div>
  )
}
