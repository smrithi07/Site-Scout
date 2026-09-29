// One survey unit, for the executive in the field: lanes numbered in walking order (the route the
// time estimate assumes) on the map and in the list, each opening its capture form; drafts that
// couldn't be sent (no network) with a "send now"; and "Submit unit" once every lane is handled.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import { useAuth } from '../../app/auth'
import MapView, { boundsOf } from '../../components/MapView'
import { fmt } from '../../components/ScoreBreakdown'
import { useMapLayers } from '../areas/AnalysePage'
import { captureBody, clearDraft, isNetworkError, queuedDrafts, saveDraft } from './captureDrafts'

const STATUS = {
  surveyed: { label: 'surveyed', chip: 'bg-emerald-100 text-emerald-900', color: '#15803d' },
  could_not_survey: { label: 'could not survey', chip: 'bg-amber-100 text-amber-900', color: '#d97706' },
  todo: { label: 'to do', chip: 'bg-brand/10 text-brand', color: '#782b90' },
}

export default function UnitPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const { state } = useLocation()
  const queryClient = useQueryClient()
  const layers = useMapLayers({ withGrid: false })
  const [msg, setMsg] = useState(state?.flash ? { tone: 'ok', text: state.flash } : null)
  const [busy, setBusy] = useState(false)
  const [, bump] = useState(0)
  const unit = useQuery({ queryKey: ['unit', id], queryFn: () => api(`/units/${id}`) })
  const lanes = useQuery({ queryKey: ['unit', id, 'segments'], queryFn: () => api(`/units/${id}/segments`) })
  const u = unit.data
  const queued = queuedDrafts(user.id, id)

  // MapLibre flattens nested properties to strings, so expose the lane's state as a plain field.
  const mapData = useMemo(() => lanes.data && ({
    ...lanes.data,
    features: lanes.data.features.map((f) => ({ ...f, properties: { ...f.properties, capture: undefined, state: f.properties.capture?.status ?? 'todo' } })),
  }), [lanes.data])
  const overlays = useMemo(() => (mapData ? [{
    id: 'unit-lanes', data: mapData, layers: [
      { id: 'unit-lanes-line', type: 'line', layout: { 'line-cap': 'round' },
        paint: { 'line-color': ['match', ['get', 'state'], ...Object.entries(STATUS).flatMap(([k, v]) => [k, v.color]), '#782b90'], 'line-width': 5 } },
      { id: 'unit-lanes-num', type: 'symbol', layout: { 'symbol-placement': 'line-center', 'text-field': ['to-string', ['get', 'order']],
          'text-font': ['Noto Sans Bold'], 'text-size': 12, 'text-allow-overlap': true },
        paint: { 'text-color': '#1c1022', 'text-halo-color': '#ffffff', 'text-halo-width': 2 } },
      { id: 'unit-lanes-hit', type: 'line', clickable: true, paint: { 'line-color': '#000', 'line-width': 18, 'line-opacity': 0.01 } },
    ],
  }] : []), [mapData])
  const fit = useMemo(() => (lanes.data?.features.length ? boundsOf(lanes.data) : null), [lanes.data])

  const refresh = () => { queryClient.invalidateQueries({ queryKey: ['unit', id] }); queryClient.invalidateQueries({ queryKey: ['my-units'] }) }
  const sendQueued = async () => {
    setBusy(true); setMsg(null)
    let sent = 0, failed = null
    for (const d of queued) {
      try {
        await api('/captures', { method: 'POST', body: captureBody(id, d.segment_id, d) })
        clearDraft(user.id, id, d.segment_id); sent++
      } catch (e) {
        if (isNetworkError(e)) { failed = 'Still no connection — the lanes stay saved on this phone.'; break }
        saveDraft(user.id, id, d.segment_id, { ...d, queued: false })   // refused: needs fixing in the form
        failed = `A lane was not accepted: ${e.message} — open it to fix.`
      }
    }
    setBusy(false); bump((x) => x + 1); refresh()
    setMsg(failed ? { tone: 'warn', text: `${sent ? `${sent} sent. ` : ''}${failed}` } : { tone: 'ok', text: `${sent} lane(s) sent.` })
  }
  const submit = async () => {
    setBusy(true); setMsg(null)
    try {
      await api(`/units/${id}/submit`, { method: 'POST' }); refresh()
      setMsg({ tone: 'ok', text: `${u.label} submitted — thank you.` })
    } catch (e) { setMsg({ tone: 'warn', text: e.message }) } finally { setBusy(false) }
  }

  // Offline in the field: keep showing the last loaded unit (and the queued lanes) — never blank it.
  if (unit.isError && !u) return <p className="p-6 text-red-700">{unit.error.message}</p>
  if (!u) return <p className="p-6">Loading…</p>
  const offline = unit.isError || lanes.isError
  const features = lanes.data?.features ?? []
  const handled = u.surveyed + u.gaps
  const allDone = handled >= u.segment_count
  const submitted = u.status === 'submitted'
  const nextLane = features.find((f) => !f.properties.capture)?.properties

  return (
    <div className="mx-auto flex max-w-xl flex-col pb-24">
      <div className="p-4 pb-2">
        <Link to="/" className="text-sm text-brand">← My units</Link>
        <h1 className="text-xl font-bold">{u.label} <span className="text-base font-normal">near {u.property.label}</span></h1>
        <p className="text-xs opacity-70">{handled} of {u.segment_count} lanes done{u.gaps > 0 && ` (${u.gaps} could not survey)`} · {fmt(u.length_m / 1000, 1)} km · ≈ {fmt(u.minutes / 60, 1)} h
          {u.pieces > 1 && ` · ${u.pieces} separate parts`}{submitted && ' · submitted'}</p>
      </div>
      {offline && <p className="mx-4 mb-2 rounded bg-stone-100 p-2 text-xs">No connection — showing what was last loaded. Captures are kept on this phone.</p>}
      {msg && <p className={`mx-4 mb-2 rounded p-2 text-sm ${msg.tone === 'ok' ? 'bg-emerald-50 text-emerald-900' : 'bg-amber-50 text-amber-900'}`}>{msg.text}</p>}
      {queued.length > 0 && (
        <div className="mx-4 mb-2 flex items-center gap-2 rounded bg-accent/40 p-2 text-sm">
          <span className="flex-1">{queued.length} lane(s) saved on this phone, not sent yet.</span>
          <button onClick={sendQueued} disabled={busy} className="rounded bg-brand px-3 py-1 font-semibold text-white disabled:opacity-40">Send now</button>
        </div>
      )}
      <div className="h-72 shrink-0">
        <MapView serviceArea={layers.serviceArea} overlays={overlays} fit={fit}
                 onOverlayClick={(f) => !submitted && f && navigate(`/units/${id}/lanes/${f.properties.segment_id}`)} />
      </div>
      <div className="flex gap-3 px-4 pt-1 text-xs">
        {Object.values(STATUS).map((s) => <span key={s.label} className="flex items-center gap-1"><span className="inline-block h-1 w-4 rounded" style={{ background: s.color }} />{s.label}</span>)}
        <a className="ml-auto text-brand underline" target="_blank" rel="noreferrer" href={`https://www.google.com/maps/dir/?api=1&destination=${u.lat},${u.lon}`}>Directions</a>
      </div>
      <ul className="space-y-1 p-4">
        {features.map(({ properties: l }) => {
          const st = STATUS[l.capture?.status ?? 'todo']
          const row = (
            <>
              <span className="w-6 text-xs opacity-60">{l.order}</span>
              <span className="min-w-0 flex-1 truncate">{l.name ?? `Unnamed ${l.highway.replaceAll('_', ' ')} lane`}
                {l.capture?.gps_distance_m > 75 && <span className="ml-1 text-xs text-amber-800">· GPS far</span>}</span>
              <span className="text-xs tabular-nums opacity-70">{fmt(l.length_m, 0)} m</span>
              <span className={`rounded px-1.5 text-xs whitespace-nowrap ${st.chip}`}>{st.label}</span>
            </>
          )
          return (
            <li key={l.segment_id}>
              {submitted
                ? <div className="flex items-center gap-2 rounded-md border border-brand/15 bg-white px-3 py-2 text-sm">{row}</div>
                : <Link to={`/units/${id}/lanes/${l.segment_id}`} className="flex items-center gap-2 rounded-md border border-brand/15 bg-white px-3 py-2.5 text-sm active:bg-brand-light">{row}</Link>}
            </li>
          )
        })}
      </ul>
      {!submitted && (
        <div className="fixed inset-x-0 bottom-0 border-t bg-white/95 p-3 backdrop-blur">
          <div className="mx-auto max-w-xl">
            {allDone
              ? <button onClick={submit} disabled={busy || queued.length > 0} className="w-full rounded-lg bg-brand py-3 font-semibold text-white disabled:opacity-40">Submit {u.label}</button>
              : nextLane && <Link to={`/units/${id}/lanes/${nextLane.segment_id}`} className="block w-full rounded-lg bg-accent py-3 text-center font-semibold text-ink">
                  Capture lane {nextLane.order}{nextLane.name ? ` · ${nextLane.name}` : ''}</Link>}
          </div>
        </div>
      )}
    </div>
  )
}
