// City-wide opportunity map (bonus): the best un-scouted pockets of Chennai without picking an area
// first. Heat = every rated selection cell; grey = already scouted (property, scout task, Savomart
// store); numbered outlines = pockets. "Run analysis" starts the M1 area report on a pocket's cells
// (its score is what that report will give); "Adjust cells" opens the analyse page pre-filled.
import { useQuery } from '@tanstack/react-query'
import { cellToBoundary, cellToLatLng } from 'h3-js'
import { useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { useAuth } from '../../app/auth'
import JobProgress from '../../components/JobProgress'
import MapView, { boundsOf } from '../../components/MapView'
import { fmt } from '../../components/ScoreBreakdown'
import { useMapLayers } from '../areas/AnalysePage'

const RATING_STYLE = { 'Strong fit': 'bg-emerald-100 text-emerald-900', 'Moderate fit': 'bg-sky-100 text-sky-900',
                       'Weak fit': 'bg-stone-200 text-stone-800' }

const polygon = (h3) => {
  const ring = cellToBoundary(h3, true)
  return { type: 'Polygon', coordinates: [[...ring, ring[0]]] }
}
const fc = (features) => ({ type: 'FeatureCollection', features })

function centre(cells) {
  const pts = cells.map((c) => cellToLatLng(c))
  return [pts.reduce((s, p) => s + p[1], 0) / pts.length, pts.reduce((s, p) => s + p[0], 0) / pts.length]
}

function overlaysFor(d, selected) {
  return [
    { id: 'opp-heat', data: fc(Object.entries(d.cell_scores).map(([h3, score]) => ({ type: 'Feature', properties: { h3, score }, geometry: polygon(h3) }))),
      layers: [{ id: 'opp-heat-fill', type: 'fill', beforeId: 'stores', paint: {
        'fill-color': ['interpolate', ['linear'], ['get', 'score'], 30, '#f3e9f6', 50, '#c79bd6', 70, '#782b90', 85, '#3d1049'],
        'fill-opacity': 0.55 } }] },
    { id: 'opp-scouted', data: fc(d.scouted.map((s) => ({ type: 'Feature', properties: { h3: s.h3, why: s.why.join(', ') }, geometry: polygon(s.h3) }))),
      layers: [
        { id: 'opp-scouted-fill', type: 'fill', beforeId: 'stores', clickable: true, paint: { 'fill-color': '#a8a29e', 'fill-opacity': 0.85 } },
        { id: 'opp-scouted-line', type: 'line', beforeId: 'stores', paint: { 'line-color': '#1c1917', 'line-width': 1, 'line-dasharray': [2, 2] } },
      ] },
    { id: 'opp-pockets', data: fc(d.pockets.flatMap((p) => p.cells.map((h3) => ({ type: 'Feature', properties: { rank: p.rank, sel: p.rank === selected }, geometry: polygon(h3) })))),
      layers: [
        { id: 'opp-pocket-fill', type: 'fill', beforeId: 'stores', clickable: true,
          paint: { 'fill-color': '#fff200', 'fill-opacity': ['case', ['get', 'sel'], 0.5, 0] } },
        { id: 'opp-pocket-line', type: 'line', beforeId: 'stores',
          paint: { 'line-color': '#1c1022', 'line-width': ['case', ['get', 'sel'], 3.5, 2.5] } },
      ] },
    { id: 'opp-ranks', data: fc(d.pockets.map((p) => ({ type: 'Feature', properties: { rank: p.rank, label: String(p.rank) }, geometry: { type: 'Point', coordinates: centre(p.cells) } }))),
      layers: [
        { id: 'opp-rank-dot', type: 'circle', clickable: true, paint: {
          'circle-radius': 11, 'circle-color': '#fff200', 'circle-stroke-color': '#1c1022', 'circle-stroke-width': 2 } },
        { id: 'opp-rank-num', type: 'symbol', layout: { 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Bold'], 'text-size': 12, 'text-allow-overlap': true },
          paint: { 'text-color': '#1c1022' } },
      ] },
  ]
}

function PocketCard({ p, selected, onSelect, cardRef }) {
  const navigate = useNavigate()
  const [job, setJob] = useState(null)
  const [error, setError] = useState(null)
  const run = async () => {
    setError(null)
    try {
      setJob((await api('/areas/reports', { method: 'POST', body: p.selection })).job_id)
    } catch (e) {
      setError(e.message)
    }
  }
  return (
    <li ref={cardRef} className={`rounded-lg border bg-white p-3 text-sm ${selected ? 'border-brand ring-2 ring-brand/30' : 'border-brand/15'}`}>
      <button onClick={onSelect} className="flex w-full items-start gap-2 text-left">
        <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent text-xs font-bold text-ink ring-2 ring-ink">{p.rank}</span>
        <span className="min-w-0 flex-1">
          <span className="block font-semibold">{p.label}</span>
          <span className="text-xs opacity-70">{p.area_km2} km² · {p.cells.length} cell{p.cells.length > 1 ? 's' : ''} · {p.confidence} confidence</span>
        </span>
        <span className="text-right">
          <span className="block text-lg leading-none font-bold tabular-nums">{fmt(p.score)}</span>
          <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap ${RATING_STYLE[p.rating]}`}>{p.rating}</span>
        </span>
      </button>
      <p className="mt-2">
        <span className="opacity-60">Why: </span>
        {p.why.map((w) => `${w.label} (top ${Math.max(1, Math.round(100 - w.normalized))}% of Chennai)`).join(' · ')}
      </p>
      <p className="mt-1 text-xs opacity-75">
        {p.facts.ml_buildings.toLocaleString('en-IN')} buildings · {p.facts.osm_competitors} grocery shops in OSM (lower bound) ·{' '}
        {p.facts.transit_stops} transit stops · nearest Savomart {p.facts.nearest_store_m != null ? `${(p.facts.nearest_store_m / 1000).toFixed(1)} km` : 'n/a'}
      </p>
      {p.analysed.length > 0 && (
        <p className="mt-1 text-xs">
          Already analysed:{' '}
          {p.analysed.slice(0, 2).map((r) => <Link key={r.report_id} to={`/areas/reports/${r.report_id}`} className="mr-2 text-brand underline">report #{r.report_id}</Link>)}
        </p>
      )}
      {job ? (
        <div className="mt-2"><JobProgress jobId={job} onSucceeded={(out) => out.report_id && navigate(`/areas/reports/${out.report_id}`)} /></div>
      ) : (
        <div className="mt-2 flex gap-2">
          <button onClick={run} className="flex-1 rounded-md bg-accent px-3 py-1.5 font-semibold text-ink shadow hover:brightness-95">Run analysis</button>
          <button onClick={() => navigate('/areas/analyse', { state: { cells: p.cells } })}
                  className="rounded-md px-3 py-1.5 font-semibold text-brand ring-1 ring-brand/40 hover:bg-brand-light">Adjust cells</button>
        </div>
      )}
      {error && <p className="mt-1 text-red-700">{error}</p>}
    </li>
  )
}

export default function OpportunitiesPage() {
  const { user } = useAuth()
  const layers = useMapLayers({ withGrid: false })
  const q = useQuery({ queryKey: ['opportunities'], queryFn: () => api('/opportunities'), enabled: user?.role === 'bd_manager' })
  const [selected, setSelected] = useState(null)
  const [fit, setFit] = useState(null)
  const [scoutedNote, setScoutedNote] = useState(null)
  const cards = useRef({})
  const mapBox = useRef(null)
  const d = q.data
  const overlays = useMemo(() => (d ? overlaysFor(d, selected) : []), [d, selected])

  if (user?.role !== 'bd_manager') return <p className="p-6">The opportunity map is for the BD Manager. Switch user in the header.</p>

  const select = (rank, { scroll = false } = {}) => {
    const p = d.pockets.find((x) => x.rank === rank)
    if (!p) return
    setSelected(rank)
    setScoutedNote(null)
    setFit(boundsOf(p.cells_geojson))
    if (scroll) cards.current[rank]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    else if (window.matchMedia('(max-width: 767px)').matches) mapBox.current?.scrollIntoView({ behavior: 'smooth' })  // phone: map is above the list
  }
  const onOverlayClick = (f, layerId) => {
    if (layerId === 'opp-scouted-fill') return setScoutedNote(f.properties.why)
    if (f.properties.rank != null) select(Number(f.properties.rank), { scroll: true })
  }

  return (
    <div className="flex h-full flex-col md:flex-row">
      <aside className="order-2 w-full overflow-y-auto border-r border-brand/10 bg-white/70 p-4 md:order-1 md:w-[28rem]">
        <h1 className="text-lg font-bold">Opportunity map</h1>
        <p className="mt-1 text-sm">The best-scoring parts of Chennai that nobody has scouted yet — no area picked first.</p>
        {q.isLoading && <p className="mt-4 text-sm opacity-70">Scoring the city…</p>}
        {q.isError && <p className="mt-4 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-800">{q.error.message}</p>}
        {d && (
          <>
            <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
              <b>Desk estimate (proxy) — nobody has visited.</b>
              <ul className="mt-1 list-disc pl-4">{d.caveats.slice(1).map((c) => <li key={c}>{c}</li>)}</ul>
            </div>
            <p className="mt-2 text-xs opacity-70">
              {d.cells_rated} cells rated · pockets grow from cells above {fmt(d.method.threshold)} (top {100 - d.method.seed_percentile}% of
              Chennai), up to {d.method.max_cells} cells · {d.cells_scouted} cells skipped as already scouted (grey) · data snapshot #{d.snapshot_id},
              config {d.config_version}
            </p>
            {scoutedNote && <p className="mt-2 rounded bg-stone-100 p-2 text-sm">Already scouted: {scoutedNote}</p>}
            {d.pockets.length === 0
              ? <p className="mt-4 text-sm">No un-scouted pocket is above the threshold right now.</p>
              : (
                <ol className="mt-3 space-y-2">
                  {d.pockets.map((p) => (
                    <PocketCard key={p.rank} p={p} selected={selected === p.rank} onSelect={() => select(p.rank)}
                                cardRef={(el) => { cards.current[p.rank] = el }} />
                  ))}
                </ol>
              )}
          </>
        )}
        <p className="mt-6 text-xs opacity-60">Darker purple = higher score. Yellow dots = existing Savomart stores; numbered circles = pockets.</p>
      </aside>
      <div ref={mapBox} className="order-1 h-72 shrink-0 md:order-2 md:h-auto md:flex-1 md:shrink">
        <MapView serviceArea={layers.serviceArea} stores={layers.stores} overlays={overlays} onOverlayClick={onOverlayClick} fit={fit} />
      </div>
    </div>
  )
}
