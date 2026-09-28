// A scout task on the map: its area, the hotspots to visit (with why), and what's been scouted.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import { useAuth } from '../../app/auth'
import MapView from '../../components/MapView'
import { fmt } from '../../components/ScoreBreakdown'
import { useMapLayers } from '../areas/AnalysePage'
import { taskOverlays } from './mapLayers'
import { boundsOf } from '../../components/MapView'

export default function TaskPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const layers = useMapLayers({ withGrid: false })
  const task = useQuery({ queryKey: ['task', id], queryFn: () => api(`/tasks/${id}`) })
  const [error, setError] = useState(null)
  const t = task.data
  const overlays = useMemo(() => (t ? taskOverlays(t) : []), [t])
  const fit = useMemo(() => (t ? boundsOf(overlays[0].data) : null), [t?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const setStatus = async (status, reason) => {
    setError(null)
    try {
      await api(`/tasks/${id}`, { method: 'PATCH', body: { version: t.version, status, reason } })
      queryClient.invalidateQueries({ queryKey: ['task', id] })
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    } catch (e) {
      setError(e.status === 409 ? 'The task changed meanwhile — refreshed, try again.' : e.message)
      queryClient.invalidateQueries({ queryKey: ['task', id] })
    }
  }

  if (task.isError) return <p className="p-6 text-red-700">{task.error.message}</p>
  if (!t) return <p className="p-6">Loading…</p>
  const isMine = t.assignee_id === user.id

  return (
    <div className="mx-auto flex h-full max-w-xl flex-col">
      <div className="h-72 shrink-0"><MapView serviceArea={layers.serviceArea} stores={layers.stores} overlays={overlays} fit={fit} /></div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4 pb-24">
        <div>
          <p className="text-xs text-brand">Scout task #{t.id} · {t.status.replace('_', ' ')}{t.due_date && ` · due ${new Date(t.due_date).toLocaleDateString('en-IN')}`}</p>
          <h1 className="text-xl font-bold">{t.title}</h1>
          {t.note && <p className="mt-1 text-sm">{t.note}</p>}
        </div>

        <section>
          <h2 className="mb-1 text-sm font-semibold">Where to look</h2>
          <ol className="space-y-2">
            {t.hotspots.map((h, i) => (
              <li key={h.h3} className="rounded-lg border border-brand/15 bg-white p-3 text-sm">
                <div className="flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-xs font-bold text-ink">{i + 1}</span>
                  <span className="font-semibold">Ward {h.ward_no}</span>
                  <a className="ml-auto text-xs text-brand underline" target="_blank" rel="noreferrer"
                     href={`https://www.google.com/maps/dir/?api=1&destination=${h.lat},${h.lon}`}>directions ↗</a>
                </div>
                <div className="mt-1 opacity-80">{h.reasons.map((x) => `${x.label} ${fmt(x.normalized, 0)}/100`).join(' · ')}</div>
              </li>
            ))}
            {t.hotspots.length === 0 && <li className="text-sm opacity-70">No specific hotspots — scout anywhere in the shaded area.</li>}
          </ol>
        </section>

        <section>
          <h2 className="mb-1 text-sm font-semibold">Scouted so far ({t.properties.length})</h2>
          <ul className="space-y-1 text-sm">
            {t.properties.map((p) => (
              <li key={p.id}><Link to={`/properties/${p.id}`} className="text-brand underline">{p.label}</Link> <span className="opacity-60">· {p.stage.replaceAll('_', ' ')}</span></li>
            ))}
          </ul>
        </section>

        {isMine && t.status === 'open' && (
          <button onClick={() => setStatus('in_progress', 'started scouting')} className="rounded-md border border-brand px-3 py-2 text-sm text-brand">Start</button>
        )}
        {isMine && t.status === 'in_progress' && (
          <button onClick={() => setStatus('done', 'scouting finished')} className="rounded-md border border-brand px-3 py-2 text-sm text-brand">Mark done</button>
        )}
        {error && <p className="text-sm text-red-700">{error}</p>}
      </div>
      {isMine && ['open', 'in_progress'].includes(t.status) && (
        <Link to={`/properties/new?task=${t.id}`} className="fixed right-4 bottom-4 left-4 mx-auto block max-w-xl rounded-full bg-accent px-4 py-3 text-center font-semibold text-ink shadow-lg">
          ＋ Add property for this task
        </Link>
      )}
    </div>
  )
}
