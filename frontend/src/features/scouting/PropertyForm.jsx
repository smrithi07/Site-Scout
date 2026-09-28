// The BD Executive's property form (docs/DESIGN.md §6), built for a phone: pin first, then the few
// fields that matter. Autosaves a draft on the phone; saving is idempotent by client_id.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../../api/client'
import { useAuth } from '../../app/auth'
import MapView, { boundsOf } from '../../components/MapView'
import { useMapLayers } from '../areas/AnalysePage'
import { deleteDraft, getDraft, saveDraft } from './drafts'
import { pinOverlay, taskOverlays } from './mapLayers'

const EMPTY = {
  label: '', address: '', landmark: '', access_notes: '', nearby_road: '', locality: '',
  monthly_rent: '', rent_unit: 'per_month', area_sqft: '', security_deposit: '', availability: '',
  frontage_ft: '', road_width_ft: '', floor: '', visibility: '', accessibility: '', parking: '', condition: '',
  owner_name: '', owner_phone: '',
}
const NUMERIC = ['monthly_rent', 'area_sqft', 'security_deposit', 'frontage_ft', 'road_width_ft']
const around = (p) => [[p.lon - 0.004, p.lat - 0.004], [p.lon + 0.004, p.lat + 0.004]]

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="text-xs font-medium opacity-70">{label}</span>
      {children}
      {hint && <span className="mt-0.5 block text-xs opacity-60">{hint}</span>}
    </label>
  )
}

const input = 'mt-0.5 w-full rounded-md border border-brand/20 bg-white px-3 py-2 text-base focus:border-brand focus:outline-none'

function Choice({ value, options, onChange, label }) {
  return (
    <div>
      <span className="text-xs font-medium opacity-70">{label}</span>
      <div className="mt-0.5 flex gap-1" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button type="button" key={o} role="radio" aria-checked={value === o} onClick={() => onChange(value === o ? '' : o)}
                  className={`flex-1 rounded-md border px-2 py-2 text-sm ${value === o ? 'border-brand bg-brand text-white' : 'border-brand/20 bg-white'}`}>
            {o.replaceAll('_', ' ').replace('sqft', 'sq ft')}
          </button>
        ))}
      </div>
    </div>
  )
}

export default function PropertyForm() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const taskId = params.get('task') ? Number(params.get('task')) : null
  const layers = useMapLayers({ withGrid: false })

  const initial = useMemo(() => {
    const d = params.get('draft') && getDraft(user.id, params.get('draft'))
    return d ?? { clientId: crypto.randomUUID(), taskId, fields: EMPTY, pin: null, device: null }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const [clientId] = useState(initial.clientId)
  const [fields, setFields] = useState({ ...EMPTY, ...initial.fields })
  const [pin, setPin] = useState(initial.pin)          // {lat, lon, accuracy}
  const [device, setDevice] = useState(initial.device) // where the executive is
  const [locating, setLocating] = useState(false)
  const [geoError, setGeoError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const task = useQuery({ queryKey: ['task', initial.taskId], queryFn: () => api(`/tasks/${initial.taskId}`), enabled: !!initial.taskId })

  // Autosave a draft on the phone (debounced) — once there's something worth keeping.
  useEffect(() => {
    if (!pin && !fields.label.trim()) return
    const t = setTimeout(() => saveDraft(user.id, { clientId, taskId: initial.taskId, fields, pin, device }), 400)
    return () => clearTimeout(t)
  }, [fields, pin, device]) // eslint-disable-line react-hooks/exhaustive-deps

  const where = useQuery({
    queryKey: ['locate', pin?.lat, pin?.lon],
    queryFn: () => api(`/reference/locate?lat=${pin.lat}&lon=${pin.lon}`),
    enabled: !!pin,
  })
  const ctx = where.data
  const pinProblem = ctx && (!ctx.in_service_area ? 'Outside the service area (GCC)' : ctx.in_landuse ? `In ${ctx.in_landuse} — move the pin` : null)
  useEffect(() => {
    if (ctx?.locality && !fields.locality) setFields((f) => ({ ...f, locality: ctx.locality }))
  }, [ctx?.locality]) // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k) => (e) => setFields((f) => ({ ...f, [k]: e?.target ? e.target.value : e }))

  const useMyLocation = () => {
    setGeoError(null)
    if (!navigator.geolocation) return setGeoError('This browser has no location access — tap the map to drop the pin.')
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const here = { lat: pos.coords.latitude, lon: pos.coords.longitude }
        setPin({ ...here, accuracy: Math.round(pos.coords.accuracy) })
        setDevice(here)
        setFit(around(here))
        setLocating(false)
      },
      (err) => { setGeoError(`Location unavailable (${err.message}) — tap the map to drop the pin.`); setLocating(false) },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 10000 },
    )
  }

  const perSqft = useMemo(() => {
    const rent = Number(fields.monthly_rent), area = Number(fields.area_sqft)
    if (!rent) return null
    return fields.rent_unit === 'per_sqft_month' ? rent : area ? rent / area : null
  }, [fields.monthly_rent, fields.area_sqft, fields.rent_unit])

  const overlays = useMemo(() => [
    ...(task.data ? taskOverlays(task.data) : []),
    ...(pin ? pinOverlay(pin.lat, pin.lon, pin.accuracy) : []),
  ], [task.data, pin])
  // Frame the pin when GPS (or a restored draft) sets it — not on every tap, which would jump the map.
  // Before there's a pin, a task's area is the natural place to start.
  const [fit, setFit] = useState(() => initial.pin && around(initial.pin))
  useEffect(() => {
    if (task.data && !pin) setFit(boundsOf(taskOverlays(task.data)[0].data))
  }, [task.data]) // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    if (!pin) return setError('Drop the pin first (use my location, or tap the map).')
    const body = { client_id: clientId, task_id: initial.taskId, lat: pin.lat, lon: pin.lon,
                   gps_accuracy_m: pin.accuracy ?? null, device_lat: device?.lat ?? null, device_lon: device?.lon ?? null }
    for (const [k, v] of Object.entries(fields)) {
      if (v === '' || v == null) body[k] = null
      else body[k] = NUMERIC.includes(k) ? Number(v) : v
    }
    if (body.monthly_rent == null) body.rent_unit = null
    setSaving(true)
    try {
      const saved = await api('/properties', { method: 'POST', body })
      deleteDraft(user.id, clientId)
      navigate(`/properties/${saved.id}?new=1`, { replace: true })
    } catch (err) {
      setError(err instanceof ApiError
        ? err.message
        : "No connection — kept as a draft on this phone. Submitting again later is safe (it won't create a duplicate).")
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto flex h-full max-w-xl flex-col">
      <div className="h-64 shrink-0">
        <MapView serviceArea={layers.serviceArea} stores={layers.stores} overlays={overlays} fit={fit}
                 onMapClick={(p) => setPin({ ...p, accuracy: null })} />
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={useMyLocation} className="rounded-md bg-brand px-3 py-2 text-sm font-semibold text-white">
            {locating ? 'Locating…' : '◎ Use my location'}
          </button>
          <span className="text-xs opacity-70">or tap the map to drop the pin</span>
        </div>
        {geoError && <p className="text-sm text-amber-800">{geoError}</p>}
        {pin && (
          <div className={`rounded-md border p-2 text-sm ${pinProblem ? 'border-red-300 bg-red-50 text-red-800' : 'border-emerald-200 bg-emerald-50'}`}>
            {pinProblem ?? (ctx
              ? <>✓ {ctx.locality ?? 'Inside GCC'} · {ctx.pincode ?? 'no pincode'} · ward {ctx.ward_no} · {ctx.zone_name} zone
                  {pin.accuracy != null && <> · GPS ±{pin.accuracy} m{pin.accuracy > 50 && ' (weak — check the pin)'}</>}</>
              : 'Checking location…')}
          </div>
        )}
        {task.data && <p className="text-sm">For task: <strong>{task.data.title}</strong></p>}

        <Field label="Property name *"><input required minLength={2} value={fields.label} onChange={set('label')} className={input} placeholder="e.g. Corner shop, 4th Main Rd" /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Locality"><input value={fields.locality} onChange={set('locality')} className={input} /></Field>
          <Field label="Nearby road"><input value={fields.nearby_road} onChange={set('nearby_road')} className={input} /></Field>
        </div>
        <Field label="Address"><input value={fields.address} onChange={set('address')} className={input} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Landmark"><input value={fields.landmark} onChange={set('landmark')} className={input} /></Field>
          <Field label="Access notes"><input value={fields.access_notes} onChange={set('access_notes')} className={input} placeholder="gate hours, entry…" /></Field>
        </div>

        <fieldset className="space-y-3 rounded-lg border border-brand/15 bg-white/60 p-3">
          <legend className="px-1 text-sm font-semibold text-brand">Commercial (BD only)</legend>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Rent (₹)"><input inputMode="decimal" value={fields.monthly_rent} onChange={set('monthly_rent')} className={input} /></Field>
            <Choice label="Rent is" value={fields.rent_unit} onChange={(v) => setFields((f) => ({ ...f, rent_unit: v || 'per_month' }))}
                    options={['per_month', 'per_sqft_month']} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Area (sq ft)"><input inputMode="decimal" value={fields.area_sqft} onChange={set('area_sqft')} className={input} /></Field>
            <Field label="Deposit (₹)"><input inputMode="decimal" value={fields.security_deposit} onChange={set('security_deposit')} className={input} /></Field>
          </div>
          {perSqft != null && ctx?.rent_band && (
            <p className={`text-xs ${perSqft < ctx.rent_band.min * 0.5 || perSqft > ctx.rent_band.max * 2 ? 'text-amber-800' : 'opacity-70'}`}>
              ≈ ₹{perSqft.toFixed(0)}/sq ft/month · {ctx.rent_band.label} band for this zone ₹{ctx.rent_band.min}–{ctx.rent_band.max}
            </p>
          )}
          <Field label="Availability"><input value={fields.availability} onChange={set('availability')} className={input} placeholder="e.g. from 1 Nov" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Owner / broker"><input value={fields.owner_name} onChange={set('owner_name')} className={input} /></Field>
            <Field label="Phone"><input type="tel" value={fields.owner_phone} onChange={set('owner_phone')} className={input} /></Field>
          </div>
        </fieldset>

        <fieldset className="space-y-3 rounded-lg border border-brand/15 bg-white/60 p-3">
          <legend className="px-1 text-sm font-semibold text-brand">Site</legend>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Frontage (ft)"><input inputMode="decimal" value={fields.frontage_ft} onChange={set('frontage_ft')} className={input} /></Field>
            <Field label="Road width (ft)"><input inputMode="decimal" value={fields.road_width_ft} onChange={set('road_width_ft')} className={input} /></Field>
            <Field label="Floor">
              <select value={fields.floor} onChange={set('floor')} className={input}>
                <option value="">—</option>{['basement', 'ground', 'first', 'upper'].map((o) => <option key={o}>{o}</option>)}
              </select>
            </Field>
          </div>
          <Choice label="Visibility" value={fields.visibility} onChange={set('visibility')} options={['poor', 'fair', 'good']} />
          <Choice label="Accessibility" value={fields.accessibility} onChange={set('accessibility')} options={['poor', 'fair', 'good']} />
          <Choice label="Parking" value={fields.parking} onChange={set('parking')} options={['none', 'limited', 'good']} />
          <Choice label="Condition" value={fields.condition} onChange={set('condition')} options={['poor', 'fair', 'good']} />
        </fieldset>

        {error && <p className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-800">{error}</p>}
        <p className="text-xs opacity-60">Draft saved on this phone automatically. Photos are added after saving.</p>
      </div>
      <div className="sticky bottom-0 border-t border-brand/10 bg-white p-3">
        <button disabled={saving || !!pinProblem} className="w-full rounded-md bg-accent px-4 py-3 font-semibold text-ink shadow enabled:hover:brightness-95 disabled:opacity-50">
          {saving ? 'Saving…' : 'Save property'}
        </button>
      </div>
    </form>
  )
}
