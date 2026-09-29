// One lane, captured on a phone (docs/DESIGN.md §7 Lane capture). Raw observations only — nothing
// is scored here. Every change autosaves to the phone; a failed send stays queued with the same
// client id. Status + GPS are required; the time band is stamped by the server.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import { useAuth } from '../../app/auth'
import MapView, { boundsOf } from '../../components/MapView'
import { fmt } from '../../components/ScoreBreakdown'
import { useMapLayers } from '../areas/AnalysePage'
import { captureBody, clearDraft, isNetworkError, loadDraft, saveDraft } from './captureDrafts'

const COUNT_MINUTES = 5
const LEVELS = [['poor', 'Poor'], ['fair', 'Fair'], ['good', 'Good']]
const GAP_REASONS = ['Gated / no access', 'Unsafe to enter', 'Under construction', 'Private road', 'Flooded']
const ANCHORS = [['school', 'School'], ['hospital', 'Hospital'], ['transit', 'Bus / rail'], ['office', 'Office'],
                 ['market', 'Market'], ['temple', 'Temple / place of worship'], ['other', 'Other']]
const EMPTY_OBS = { pedestrians_counted: 0, count_minutes: COUNT_MINUTES, residential_units: 0, businesses: 0,
                    grocery_food_stores: 0, anchors: [], road_width_band: null, pedestrian_access: null,
                    vehicle_access: null, parking: null }

function Segmented({ label, value, options, onChange }) {
  return (
    <div>
      <p className="mb-1 text-sm font-medium">{label}</p>
      <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }} role="radiogroup" aria-label={label}>
        {options.map(([v, l]) => (
          <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(v)}
                  className={`rounded-md py-2.5 text-sm ${value === v ? 'bg-brand font-semibold text-white' : 'bg-white ring-1 ring-brand/20'}`}>{l}</button>
        ))}
      </div>
    </div>
  )
}

function Stepper({ label, hint, value, onChange }) {
  return (
    <div className="flex items-center gap-2">
      <div className="min-w-0 flex-1"><p className="text-sm font-medium">{label}</p>{hint && <p className="text-xs opacity-60">{hint}</p>}</div>
      <button type="button" aria-label={`${label} minus one`} onClick={() => onChange(Math.max(0, value - 1))} className="h-11 w-11 rounded-md bg-white text-xl ring-1 ring-brand/20">−</button>
      <input type="number" inputMode="numeric" min={0} aria-label={label} value={value} onChange={(e) => onChange(Math.max(0, Number(e.target.value) || 0))}
             className="h-11 w-16 rounded-md border text-center text-lg tabular-nums" />
      <button type="button" aria-label={`${label} plus one`} onClick={() => onChange(value + 1)} className="h-11 w-11 rounded-md bg-white text-xl ring-1 ring-brand/20">+</button>
    </div>
  )
}

function useNow(active) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(t)
  }, [active])
  return now
}

function PedestrianCount({ d, set }) {
  const started = d.count?.started_at
  const total = COUNT_MINUTES * 60 * 1000
  const now = useNow(!!started && !d.count?.done)
  const left = started ? Math.max(0, total - (now - started)) : total
  const running = !!started && !d.count?.done && left > 0
  useEffect(() => {
    if (started && !d.count?.done && left === 0) set((x) => ({ ...x, count: { ...x.count, done: true } }))
  }, [left, started, d.count?.done, set])
  const add = () => set((x) => ({ ...x, obs: { ...x.obs, pedestrians_counted: x.obs.pedestrians_counted + 1 } }))
  const mm = String(Math.floor(left / 60000)).padStart(1, '0'), ss = String(Math.floor((left % 60000) / 1000)).padStart(2, '0')

  if (d.count?.manual) {
    return (
      <div className="space-y-2 rounded-lg bg-white p-3 ring-1 ring-brand/15">
        <Stepper label="People counted" value={d.obs.pedestrians_counted} onChange={(v) => set((x) => ({ ...x, obs: { ...x.obs, pedestrians_counted: v } }))} />
        <Stepper label="Over how many minutes" value={d.obs.count_minutes} onChange={(v) => set((x) => ({ ...x, obs: { ...x.obs, count_minutes: Math.max(1, Math.min(30, v)) } }))} />
        <button type="button" onClick={() => set((x) => ({ ...x, count: null, obs: { ...x.obs, pedestrians_counted: 0, count_minutes: COUNT_MINUTES } }))} className="text-xs text-brand underline">Use the timer instead</button>
      </div>
    )
  }
  return (
    <div className="rounded-lg bg-white p-3 text-center ring-1 ring-brand/15">
      <p className="text-sm font-medium">Pedestrian count · {COUNT_MINUTES} minutes</p>
      <p className="text-xs opacity-60">Stand mid-lane and tap once for every person who passes.</p>
      {!started && (
        <div className="mt-2 space-y-1">
          <button type="button" onClick={() => set((x) => ({ ...x, count: { started_at: Date.now(), done: false }, obs: { ...x.obs, pedestrians_counted: 0, count_minutes: COUNT_MINUTES } }))}
                  className="w-full rounded-lg bg-brand py-3 font-semibold text-white">Start {COUNT_MINUTES}-minute count</button>
          <button type="button" onClick={() => set((x) => ({ ...x, count: { manual: true } }))} className="text-xs text-brand underline">I counted another way — enter it</button>
        </div>
      )}
      {started && (
        <>
          <p className={`mt-1 text-3xl font-bold tabular-nums ${running ? '' : 'text-emerald-800'}`}>{running ? `${mm}:${ss}` : 'Done'}</p>
          <button type="button" onClick={add} disabled={!running} aria-label="Count one person"
                  className="mt-2 h-28 w-full rounded-xl bg-accent text-4xl font-bold text-ink active:brightness-90 disabled:opacity-50">
            +1 <span className="block text-base font-normal">{d.obs.pedestrians_counted} counted</span>
          </button>
          {running && (
            <div className="mt-1 flex justify-center gap-4 text-xs">
              <button type="button" onClick={() => set((x) => ({ ...x, obs: { ...x.obs, pedestrians_counted: Math.max(0, x.obs.pedestrians_counted - 1) } }))} className="underline">undo one</button>
              <button type="button" onClick={() => set((x) => ({ ...x, count: null, obs: { ...x.obs, pedestrians_counted: 0 } }))} className="underline">cancel count</button>
            </div>
          )}
          {!running && <button type="button" onClick={() => set((x) => ({ ...x, count: null, obs: { ...x.obs, pedestrians_counted: 0 } }))} className="mt-1 block w-full text-xs text-brand underline">Count again</button>}
        </>
      )}
    </div>
  )
}

export default function CaptureForm() {
  const { id: unitId, segmentId } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const { state } = useLocation()
  const queryClient = useQueryClient()
  const layers = useMapLayers({ withGrid: false })
  const unit = useQuery({ queryKey: ['unit', unitId], queryFn: () => api(`/units/${unitId}`) })
  const lanes = useQuery({ queryKey: ['unit', unitId, 'segments'], queryFn: () => api(`/units/${unitId}/segments`) })
  const lane = lanes.data?.features.find((f) => f.properties.segment_id === segmentId)
  const [d, setD] = useState(() => loadDraft(user.id, unitId, segmentId) ?? {
    client_id: crypto.randomUUID(), status: null, reason: '', obs: EMPTY_OBS, count: null, gps: null, notes: '', captured_at: null })
  const [gpsError, setGpsError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const touched = useRef(false)

  // Autosave (after the first real change, so opening a lane doesn't create a draft).
  useEffect(() => { if (touched.current) saveDraft(user.id, unitId, segmentId, d) }, [d, user.id, unitId, segmentId])
  const set = (fn) => { touched.current = true; setD(fn) }

  useEffect(() => {
    if (!('geolocation' in navigator)) { setGpsError('This browser has no location service.'); return }
    const w = navigator.geolocation.watchPosition(
      (p) => { setGpsError(null); setD((x) => (x.gps?.manual ? x : { ...x, gps: { lat: p.coords.latitude, lon: p.coords.longitude, accuracy: Math.round(p.coords.accuracy) } })) },
      (e) => setGpsError(e.code === 1 ? 'Location is blocked. Allow it for this site, or tap your position on the map.' : 'No GPS fix yet. Keep the phone outdoors, or tap your position on the map.'),
      { enableHighAccuracy: true, maximumAge: 10000, timeout: 20000 })
    return () => navigator.geolocation.clearWatch(w)
  }, [])

  const overlays = useMemo(() => {
    if (!lane) return []
    const out = [{ id: 'lane', data: lane, layers: [
      { id: 'lane-halo', type: 'line', layout: { 'line-cap': 'round' }, paint: { 'line-color': '#fff200', 'line-width': 12 } },
      { id: 'lane-line', type: 'line', layout: { 'line-cap': 'round' }, paint: { 'line-color': '#782b90', 'line-width': 5 } }] }]
    if (d.gps) out.push({ id: 'me', data: { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [d.gps.lon, d.gps.lat] } },
                          layers: [{ id: 'me-dot', type: 'circle', paint: { 'circle-radius': 7, 'circle-color': '#1d4ed8', 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } }] })
    return out
  }, [lane, d.gps])
  const fit = useMemo(() => {
    if (!lane) return null
    const [[x0, y0], [x1, y1]] = boundsOf(lane)
    return [[x0 - 0.0015, y0 - 0.0015], [x1 + 0.0015, y1 + 0.0015]]
  }, [lane])

  if (unit.isError && !unit.data) return <p className="p-6 text-red-700">{unit.error.message}</p>   // cached data wins offline
  if (!unit.data || !lanes.data) return <p className="p-6">Loading…</p>
  if (!lane) return <p className="p-6">This lane isn't in {unit.data.label}. <Link to={`/units/${unitId}`} className="underline">Back</Link></p>
  const l = lane.properties
  const o = d.obs
  const missing = [
    !d.gps && 'your location',
    !d.status && 'whether you surveyed the lane',
    d.status === 'could_not_survey' && !d.reason?.trim() && 'why it could not be surveyed',
    d.status === 'surveyed' && !(d.count?.done || d.count?.manual) && 'the pedestrian count',
    d.status === 'surveyed' && !o.road_width_band && 'road width',
    d.status === 'surveyed' && !o.pedestrian_access && 'pedestrian access',
    d.status === 'surveyed' && !o.vehicle_access && 'vehicle access',
    d.status === 'surveyed' && !o.parking && 'parking',
  ].filter(Boolean)

  const next = () => {
    const todo = lanes.data.features.map((f) => f.properties)
      .filter((x) => !x.capture && x.segment_id !== segmentId)
    return todo.find((x) => x.order > l.order) ?? todo[0]
  }

  const save = async () => {
    setBusy(true); setError(null)
    const draft = { ...d, captured_at: d.captured_at ?? new Date().toISOString() }   // fixed from the first send on
    setD(draft); saveDraft(user.id, unitId, segmentId, draft)
    try {
      const r = await api('/captures', { method: 'POST', body: captureBody(unitId, segmentId, draft) })
      clearDraft(user.id, unitId, segmentId)
      queryClient.invalidateQueries({ queryKey: ['unit', unitId] }); queryClient.invalidateQueries({ queryKey: ['my-units'] })
      const n = next()
      const flash = [`Lane ${l.order} saved (${r.time_band}).`, ...r.warnings.map((w) => w.message)].join(' ')
      navigate(n ? `/units/${unitId}/lanes/${n.segment_id}` : `/units/${unitId}`, { state: { flash }, replace: true })
    } catch (e) {
      if (isNetworkError(e)) {
        saveDraft(user.id, unitId, segmentId, { ...draft, queued: true })
        navigate(`/units/${unitId}`, { state: { flash: `No connection — lane ${l.order} is saved on this phone and will be sent from the unit page.` } })
      } else setError(e.message)
    } finally { setBusy(false) }
  }

  return (
    <div className="mx-auto max-w-xl pb-28">
      <div className="px-4 pt-3">
        {state?.flash && <p className="mb-2 rounded bg-emerald-50 p-2 text-sm text-emerald-900">✓ {state.flash}</p>}
        <Link to={`/units/${unitId}`} className="text-sm text-brand">← {unit.data.label}</Link>
        <h1 className="text-lg font-bold">Lane {l.order} of {unit.data.segment_count} · {l.name ?? `unnamed ${l.highway.replaceAll('_', ' ')}`}</h1>
        <p className="text-xs opacity-70">{fmt(l.length_m, 0)} m{l.capture && ` · already captured (${l.capture.status.replaceAll('_', ' ')}) — saving again replaces it`}</p>
      </div>
      <div className="mt-2 h-44"><MapView serviceArea={layers.serviceArea} overlays={overlays} fit={fit}
        onMapClick={(p) => set((x) => ({ ...x, gps: { lat: p.lat, lon: p.lon, accuracy: null, manual: true } }))} /></div>
      <p className={`px-4 pt-1 text-xs ${d.gps ? 'opacity-70' : 'text-amber-800'}`}>
        {d.gps ? (d.gps.manual ? '📍 Position set by tapping the map (recorded as manual)' : `📍 GPS fix ±${d.gps.accuracy} m`) : gpsError ?? 'Finding your location…'}
      </p>

      <div className="space-y-4 p-4">
        <Segmented label="Lane status" value={d.status} onChange={(v) => set((x) => ({ ...x, status: v }))}
                   options={[['surveyed', 'Surveyed'], ['could_not_survey', 'Could not survey']]} />

        {d.status === 'could_not_survey' && (
          <div className="space-y-2">
            <div className="flex flex-wrap gap-1.5">
              {GAP_REASONS.map((r) => (
                <button key={r} type="button" onClick={() => set((x) => ({ ...x, reason: r }))}
                        className={`rounded-full px-3 py-1.5 text-sm ${d.reason === r ? 'bg-brand text-white' : 'bg-white ring-1 ring-brand/20'}`}>{r}</button>
              ))}
            </div>
            <input value={d.reason} onChange={(e) => set((x) => ({ ...x, reason: e.target.value }))} maxLength={300}
                   placeholder="Reason (required)" aria-label="Reason" className="w-full rounded-md border px-3 py-2" />
            <p className="text-xs opacity-60">Counts as handled, not covered. It won't be sent again until the data goes stale.</p>
          </div>
        )}

        {d.status === 'surveyed' && (
          <>
            <PedestrianCount d={d} set={set} />
            <div className="space-y-3 rounded-lg bg-brand-light/60 p-3">
              <Stepper label="Residential units" hint="homes / flats you can see on this lane" value={o.residential_units}
                       onChange={(v) => set((x) => ({ ...x, obs: { ...x.obs, residential_units: v } }))} />
              <Stepper label="Businesses" hint="shops, offices, clinics…" value={o.businesses}
                       onChange={(v) => set((x) => ({ ...x, obs: { ...x.obs, businesses: v } }))} />
              <Stepper label="Grocery / food stores" hint="kirana, supermarket, bakery, food stalls" value={o.grocery_food_stores}
                       onChange={(v) => set((x) => ({ ...x, obs: { ...x.obs, grocery_food_stores: v } }))} />
            </div>
            <div>
              <p className="mb-1 text-sm font-medium">Anchors on this lane <span className="font-normal opacity-60">(tap to add)</span></p>
              <div className="flex flex-wrap gap-1.5">
                {ANCHORS.map(([t, label]) => (
                  <button key={t} type="button" onClick={() => set((x) => ({ ...x, obs: { ...x.obs, anchors: [...x.obs.anchors, { type: t, name: null }] } }))}
                          className="rounded-full bg-white px-3 py-1.5 text-sm ring-1 ring-brand/20">+ {label}</button>
                ))}
              </div>
              {o.anchors.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {o.anchors.map((a, i) => (
                    <li key={i} className="flex items-center gap-2 text-sm">
                      <span className="w-24 shrink-0 font-medium">{ANCHORS.find(([t]) => t === a.type)[1]}</span>
                      <input value={a.name ?? ''} maxLength={120} placeholder="name (optional)" aria-label={`Name of ${a.type}`}
                             onChange={(e) => set((x) => ({ ...x, obs: { ...x.obs, anchors: x.obs.anchors.map((y, j) => (j === i ? { ...y, name: e.target.value || null } : y)) } }))}
                             className="min-w-0 flex-1 rounded border px-2 py-1" />
                      <button type="button" aria-label="remove" onClick={() => set((x) => ({ ...x, obs: { ...x.obs, anchors: x.obs.anchors.filter((_, j) => j !== i) } }))} className="px-2 text-lg">×</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <Segmented label="Road width" value={o.road_width_band} onChange={(v) => set((x) => ({ ...x, obs: { ...x.obs, road_width_band: v } }))}
                       options={[['narrow', 'Narrow'], ['medium', 'Medium'], ['wide', 'Wide']]} />
            <Segmented label="Pedestrian access" value={o.pedestrian_access} onChange={(v) => set((x) => ({ ...x, obs: { ...x.obs, pedestrian_access: v } }))} options={LEVELS} />
            <Segmented label="Vehicle access" value={o.vehicle_access} onChange={(v) => set((x) => ({ ...x, obs: { ...x.obs, vehicle_access: v } }))} options={LEVELS} />
            <Segmented label="Parking" value={o.parking} onChange={(v) => set((x) => ({ ...x, obs: { ...x.obs, parking: v } }))}
                       options={[['none', 'None'], ['limited', 'Limited'], ['good', 'Good']]} />
          </>
        )}
        {d.status && (
          <textarea value={d.notes} onChange={(e) => set((x) => ({ ...x, notes: e.target.value }))} rows={2} maxLength={1000}
                    placeholder="Notes (optional)" aria-label="Notes" className="w-full rounded-md border px-3 py-2 text-sm" />
        )}
        {error && <p className="rounded bg-red-50 p-2 text-sm text-red-800">{error}</p>}
      </div>

      <div className="fixed inset-x-0 bottom-0 border-t bg-white/95 p-3 backdrop-blur">
        <div className="mx-auto max-w-xl">
          {missing.length > 0 && <p className="mb-1 text-xs text-amber-800">Still needed: {missing.join(', ')}</p>}
          <button onClick={save} disabled={busy || missing.length > 0}
                  className="w-full rounded-lg bg-brand py-3 font-semibold text-white disabled:opacity-40">{busy ? 'Saving…' : 'Save lane'}</button>
          <p className="mt-1 text-center text-[11px] opacity-60">Saved on this phone as you go.</p>
        </div>
      </div>
    </div>
  )
}

/** Route element: a fresh form (and draft) per lane, even when moving lane → lane on one route. */
export function CaptureRoute() {
  const { segmentId } = useParams()
  return <CaptureForm key={segmentId} />
}
