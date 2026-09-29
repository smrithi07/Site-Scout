// One survey unit, for the executive in the field: the lanes on a map (done vs to do), numbered in
// walking order (the route the time estimate assumes), the lane list, and directions. Lane capture
// (one form per lane) arrives in Phase 10.
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import MapView, { boundsOf } from '../../components/MapView'
import { fmt } from '../../components/ScoreBreakdown'
import { useMapLayers } from '../areas/AnalysePage'

export default function UnitPage() {
  const { id } = useParams()
  const layers = useMapLayers({ withGrid: false })
  const [picked, setPicked] = useState(null)
  const unit = useQuery({ queryKey: ['unit', id], queryFn: () => api(`/units/${id}`) })
  const lanes = useQuery({ queryKey: ['unit', id, 'segments'], queryFn: () => api(`/units/${id}/segments`) })
  const u = unit.data
  const overlays = useMemo(() => (lanes.data ? [{
    id: 'unit-lanes', data: lanes.data, layers: [
      { id: 'unit-picked', type: 'line', layout: { 'line-cap': 'round' }, filter: ['==', ['get', 'segment_id'], picked ?? ''], paint: { 'line-color': '#fff200', 'line-width': 12 } },
      { id: 'unit-lanes-line', type: 'line', layout: { 'line-cap': 'round' },
        paint: { 'line-color': ['case', ['get', 'captured'], '#15803d', '#782b90'], 'line-width': 5 } },
      { id: 'unit-lanes-num', type: 'symbol', layout: { 'symbol-placement': 'line-center', 'text-field': ['to-string', ['get', 'order']],
          'text-font': ['Noto Sans Bold'], 'text-size': 12, 'text-allow-overlap': true },
        paint: { 'text-color': '#1c1022', 'text-halo-color': '#ffffff', 'text-halo-width': 2 } },
      { id: 'unit-lanes-hit', type: 'line', clickable: true, paint: { 'line-color': '#000', 'line-width': 18, 'line-opacity': 0.01 } },
    ],
  }] : []), [lanes.data, picked])
  const fit = useMemo(() => (lanes.data?.features.length ? boundsOf(lanes.data) : null), [lanes.data])

  if (unit.isError) return <p className="p-6 text-red-700">{unit.error.message}</p>
  if (!u) return <p className="p-6">Loading…</p>
  const features = lanes.data?.features ?? []

  return (
    <div className="mx-auto flex h-full max-w-xl flex-col">
      <div className="p-4 pb-2">
        <Link to="/" className="text-sm text-brand">← My units</Link>
        <h1 className="text-xl font-bold">{u.label} <span className="text-base font-normal">near {u.property.label}</span></h1>
        <p className="text-xs opacity-70">{u.surveyed + u.gaps} of {u.segment_count} lanes done · {fmt(u.length_m / 1000, 1)} km · ≈ {fmt(u.minutes / 60, 1)} h
          {u.pieces > 1 && ` · ${u.pieces} separate parts`}</p>
      </div>
      <div className="h-72 shrink-0 md:h-96">
        <MapView serviceArea={layers.serviceArea} overlays={overlays} fit={fit}
                 onOverlayClick={(f) => setPicked(f?.properties.segment_id ?? null)} />
      </div>
      <div className="flex gap-3 px-4 pt-1 text-xs">
        <span className="flex items-center gap-1"><span className="inline-block h-1 w-4 rounded bg-brand" />to do</span>
        <span className="flex items-center gap-1"><span className="inline-block h-1 w-4 rounded bg-emerald-700" />done</span>
        <a className="ml-auto text-brand underline" target="_blank" rel="noreferrer"
           href={`https://www.google.com/maps/dir/?api=1&destination=${u.lat},${u.lon}`}>Directions to the area</a>
      </div>
      <ul className="flex-1 space-y-1 overflow-y-auto p-4">
        {features.map(({ properties: l }) => (
          <li key={l.segment_id}>
            <button onClick={() => setPicked(l.segment_id)}
                    className={`flex w-full items-center gap-2 rounded-md border bg-white px-3 py-2 text-left text-sm ${picked === l.segment_id ? 'border-brand ring-2 ring-accent' : 'border-brand/15'}`}>
              <span className="w-6 text-xs opacity-60">{l.order}</span>
              <span className="min-w-0 flex-1 truncate">{l.name ?? `Unnamed ${l.highway.replaceAll('_', ' ')} lane`}</span>
              <span className="text-xs tabular-nums opacity-70">{fmt(l.length_m, 0)} m</span>
              <span className={`rounded px-1.5 text-xs ${l.captured ? 'bg-emerald-100 text-emerald-900' : 'bg-brand/10 text-brand'}`}>{l.captured ? 'done' : 'to do'}</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="px-4 pb-4 text-xs opacity-60">Capturing a lane (the one-lane form) arrives in the next phase.</p>
    </div>
  )
}
