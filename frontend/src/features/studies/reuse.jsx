// Shared vocabulary for catchment reuse (docs/DESIGN.md §7): segment states, reuse modes, the
// coverage bar and the catchment map layers. Numbers always come from the API's reuse summary.
import { fmt } from '../../components/ScoreBreakdown'

export const STATE = {
  fresh: { label: 'Fresh — reused', color: '#15803d', text: 'text-emerald-800' },
  fresh_gap: { label: 'Could not survey recently', color: '#d97706', text: 'text-amber-800' },
  stale: { label: 'Stale — resurvey', color: '#dc2626', text: 'text-red-800' },
  uncovered: { label: 'Never surveyed', color: '#782b90', text: 'text-brand' },
}
export const STATE_ORDER = ['fresh', 'fresh_gap', 'stale', 'uncovered']

export const MODES = {
  reuse_and_fill: { label: 'Reuse + survey the gaps', help: 'Reuse fresh data; survey stale and never-surveyed lanes.' },
  reuse_only: { label: 'Reuse only', help: 'Survey nothing new. The summary gets a lower-confidence label.' },
  full_survey: { label: 'Full survey', help: 'Ignore past data and survey every lane.' },
}
export const DEFAULT_MODE = 'reuse_and_fill'

export const STUDY_STATUS = {
  requested: { label: 'awaiting plan', style: 'bg-accent text-ink' },
  planned: { label: 'planned', style: 'bg-brand/15 text-brand' },
  in_progress: { label: 'surveying', style: 'bg-sky-100 text-sky-900' },
  complete: { label: 'complete', style: 'bg-emerald-100 text-emerald-900' },
  cancelled: { label: 'cancelled', style: 'bg-stone-200 text-stone-700' },
}

export function StatusBadge({ status }) {
  const s = STUDY_STATUS[status] ?? { label: status, style: 'bg-stone-100' }
  return <span className={`rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${s.style}`}>{s.label}</span>
}

/** Length-weighted bar of the four segment states, the design's one-line message, and the oldest reused age. */
export function CoverageBar({ reuse, compact = false }) {
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-stone-100" role="img" aria-label={reuse.message}>
        {STATE_ORDER.map((k) => reuse.pct[k] > 0 && (
          <div key={k} style={{ width: `${reuse.pct[k]}%`, background: STATE[k].color }} title={`${STATE[k].label}: ${reuse.pct[k]}%`} />
        ))}
      </div>
      <p className="mt-1.5 text-sm font-medium">{reuse.message}</p>
      {!compact && (
        <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
          {STATE_ORDER.map((k) => (
            <li key={k} className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: STATE[k].color }} />
              {STATE[k].label}: {reuse.counts[k]} lanes · {fmt(reuse.length_m[k] / 1000, 1)} km
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-xs opacity-70">
        {reuse.oldest_reused_days != null ? `Oldest reused data: ${Math.round(reuse.oldest_reused_days)} days` : 'No fresh data to reuse'}
        {' · '}fresh = surveyed within {reuse.freshness_days} days
        {' · '}{reuse.meets_threshold ? `meets the ${reuse.threshold * 100}% reuse threshold` : `below the ${reuse.threshold * 100}% reuse threshold`}
      </p>
    </div>
  )
}

/** Why a mode choice needs a reason — mirrors the server's rule so the button can say so up front. */
export function reasonNeeded(mode, { requestedMode = DEFAULT_MODE, reuse }) {
  if (mode !== requestedMode) return true
  return mode === 'reuse_only' && !reuse.meets_threshold
}

export function circle(lat, lon, radiusM, n = 64) {
  const pts = []
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * 2 * Math.PI
    pts.push([lon + (radiusM / (111320 * Math.cos((lat * Math.PI) / 180))) * Math.cos(a), lat + (radiusM / 110574) * Math.sin(a)])
  }
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [pts] } }
}

/** Catchment map overlays: circle + segments coloured by reuse state (to-survey lanes drawn thicker). */
export function catchmentOverlays(study, segments) {
  return [
    {
      id: 'catchment',
      data: circle(study.lat, study.lon, study.radius_m),
      layers: [{ id: 'catchment-line', type: 'line', paint: { 'line-color': '#1c1022', 'line-width': 1.5, 'line-dasharray': [2, 2] } }],
    },
    {
      id: 'segments',
      data: segments,
      layers: [{
        id: 'segments-line', type: 'line', layout: { 'line-cap': 'round' },
        paint: {
          'line-color': ['match', ['get', 'reuse_state'], ...STATE_ORDER.flatMap((k) => [k, STATE[k].color]), '#888'],
          'line-width': ['case', ['get', 'to_survey'], 4, 2],
          'line-opacity': ['case', ['get', 'to_survey'], 0.95, 0.55],
        },
      }],
    },
    {
      id: 'study-pin',
      data: { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [study.lon, study.lat] } },
      layers: [{ id: 'study-pin-dot', type: 'circle', paint: { 'circle-radius': 7, 'circle-color': '#fff200', 'circle-stroke-color': '#1c1022', 'circle-stroke-width': 2 } }],
    },
  ]
}

// Unit colours (tab10): distinct from each other; reused lanes stay thin grey in the unit view.
export const UNIT_COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#17becf', '#bcbd22', '#7f7f7f']
export const unitColor = (units, id) => UNIT_COLORS[Math.max(0, units.findIndex((u) => u.id === id)) % UNIT_COLORS.length]

/** Unit view: lanes coloured by unit, the focused unit emphasised, selected lanes outlined yellow.
 *  The wide invisible `segments-hit` layer is the click target (thin lines are hard to tap). */
export function unitOverlays(study, segments, units, { selected = new Set(), focus = null } = {}) {
  const colorBy = units.length
    ? ['match', ['coalesce', ['get', 'unit_id'], -1], ...units.flatMap((u) => [u.id, unitColor(units, u.id)]), '#9ca3af']
    : '#9ca3af'
  return [
    {
      id: 'catchment',
      data: circle(study.lat, study.lon, study.radius_m),
      layers: [{ id: 'catchment-line', type: 'line', paint: { 'line-color': '#1c1022', 'line-width': 1.5, 'line-dasharray': [2, 2] } }],
    },
    {
      id: 'segments',
      data: segments,
      layers: [
        { id: 'segments-selected', type: 'line', layout: { 'line-cap': 'round' }, filter: ['in', ['get', 'segment_id'], ['literal', [...selected]]],
          paint: { 'line-color': '#fff200', 'line-width': 11 } },
        { id: 'segments-line', type: 'line', layout: { 'line-cap': 'round' },
          paint: {
            'line-color': colorBy,
            'line-width': ['case', ['!', ['get', 'to_survey']], 1.5, focus != null && ['==', ['get', 'unit_id'], focus], 6, 4],
            'line-opacity': ['case', ['!', ['get', 'to_survey']], 0.5, focus == null ? true : ['==', ['get', 'unit_id'], focus], 1, 0.35],
          } },
        { id: 'segments-hit', type: 'line', clickable: true, filter: ['get', 'to_survey'], paint: { 'line-color': '#000', 'line-width': 16, 'line-opacity': 0.01 } },
      ],
    },
    {
      id: 'study-pin',
      data: { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [study.lon, study.lat] } },
      layers: [{ id: 'study-pin-dot', type: 'circle', paint: { 'circle-radius': 7, 'circle-color': '#fff200', 'circle-stroke-color': '#1c1022', 'circle-stroke-width': 2 } }],
    },
  ]
}
