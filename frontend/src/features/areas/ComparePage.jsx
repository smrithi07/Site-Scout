// Side-by-side comparison of two saved reports. Flags say whether a difference could come from the
// data snapshot or the config rather than the area itself.
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import MapView, { boundsOf } from '../../components/MapView'
import ProvenanceBadge from '../../components/ProvenanceBadge'
import { fmt } from '../../components/ScoreBreakdown'
import { useMapLayers } from './AnalysePage'
import { reportOverlays } from './reportLayers'

const FLAG_TEXT = {
  different_area: 'These are different areas.',
  different_data_snapshot: 'They use different data snapshots — part of any difference is newer data, not the area.',
  different_config: 'They use different scoring configs (weights/thresholds) — part of any difference is the rules changing.',
}

function Delta({ value, invert = false }) {
  if (value == null || value === 0) return <span className="opacity-50">{value === 0 ? '0' : '—'}</span>
  const good = invert ? value < 0 : value > 0
  return <span className={`font-semibold tabular-nums ${good ? 'text-emerald-700' : 'text-red-700'}`}>{value > 0 ? '+' : ''}{fmt(value)}</span>
}

export default function ComparePage() {
  const { a, b } = useParams()
  const layers = useMapLayers()
  const cmp = useQuery({ queryKey: ['compare', a, b], queryFn: () => api(`/areas/reports/${a}/compare/${b}`) })
  const ra = useQuery({ queryKey: ['report', a], queryFn: () => api(`/areas/reports/${a}`) })
  const rb = useQuery({ queryKey: ['report', b], queryFn: () => api(`/areas/reports/${b}`) })

  const overlays = useMemo(() => (ra.data && rb.data ? [
    ...reportOverlays(ra.data, { idPrefix: 'a', color: '#782b90', heat: false }),
    ...reportOverlays(rb.data, { idPrefix: 'b', color: '#d4a800', heat: false }),
  ] : []), [ra.data, rb.data])
  const fit = useMemo(() => {
    if (!ra.data || !rb.data) return null
    const [p, q] = [boundsOf(ra.data.cells_geojson), boundsOf(rb.data.cells_geojson)]
    return [[Math.min(p[0][0], q[0][0]), Math.min(p[0][1], q[0][1])], [Math.max(p[1][0], q[1][0]), Math.max(p[1][1], q[1][1])]]
  }, [ra.data, rb.data])

  if (cmp.isError) return <p className="p-6 text-red-700">{cmp.error.message}</p>
  if (!cmp.data) return <p className="p-6">Loading comparison…</p>
  const c = cmp.data

  const Side = ({ s, swatch }) => (
    <div className="flex-1 rounded-lg border border-brand/15 bg-white p-3">
      <div className="flex items-center gap-2 text-xs"><span className={`h-2.5 w-2.5 rounded-full ${swatch}`} /> v{s.version} · {new Date(s.created_at).toLocaleDateString('en-IN')}</div>
      <Link to={`/areas/reports/${s.id}`} className="font-semibold hover:underline">{s.label}</Link>
      <div className="mt-1 text-3xl font-bold text-brand tabular-nums">{s.score != null ? fmt(s.score) : '—'}</div>
      <div className="text-sm">{s.rating ?? s.status.replace('_', ' ')}{s.confidence && ` · ${s.confidence} confidence`}</div>
      <div className="mt-1 text-xs opacity-60">snapshot #{s.snapshot_id} · config {s.config_version}</div>
    </div>
  )

  return (
    <div className="flex h-full flex-col md:flex-row">
      <div className="order-2 min-h-0 flex-1 overflow-y-auto p-4 md:order-1 md:p-6">
        <h1 className="text-xl font-bold">Compare reports</h1>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row">
          <Side s={c.a} swatch="bg-brand" />
          <div className="self-center text-center">
            <div className="text-xs opacity-60">B − A</div>
            <div className="text-xl"><Delta value={c.score_delta} /></div>
          </div>
          <Side s={c.b} swatch="bg-[#d4a800]" />
        </div>
        {c.flags.map((f) => <p key={f} className="mt-2 text-sm text-amber-800">⚠ {FLAG_TEXT[f] ?? f}</p>)}

        <h2 className="mt-6 mb-2 text-sm font-semibold tracking-wide text-brand uppercase">Factor by factor</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase opacity-60">
                <th className="py-2 pr-3 font-medium">Factor</th>
                <th className="py-2 pr-3 font-medium">A normalised</th>
                <th className="py-2 pr-3 font-medium">B normalised</th>
                <th className="py-2 pr-3 font-medium">Δ</th>
                <th className="py-2 pr-3 font-medium">A points</th>
                <th className="py-2 pr-3 font-medium">B points</th>
                <th className="py-2 font-medium">Δ points</th>
              </tr>
            </thead>
            <tbody>
              {c.factors.map((f) => (
                <tr key={f.factor} className="border-b align-top">
                  <td className="py-2 pr-3">
                    <div className="font-medium">{f.label}</div>
                    {f.a_provenance !== f.b_provenance && (
                      <div className="mt-0.5 flex gap-1"><ProvenanceBadge value={f.a_provenance} /><ProvenanceBadge value={f.b_provenance} /></div>
                    )}
                  </td>
                  <td className="py-2 pr-3 tabular-nums">{fmt(f.a_normalized)}</td>
                  <td className="py-2 pr-3 tabular-nums">{fmt(f.b_normalized)}</td>
                  <td className="py-2 pr-3"><Delta value={f.normalized_delta} /></td>
                  <td className="py-2 pr-3 tabular-nums">{fmt(f.a_contribution)}</td>
                  <td className="py-2 pr-3 tabular-nums">{fmt(f.b_contribution)}</td>
                  <td className="py-2"><Delta value={f.contribution_delta} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2 className="mt-6 mb-2 text-sm font-semibold tracking-wide text-brand uppercase">Facts</h2>
        <table className="w-full text-sm">
          <tbody>
            {[['ml_buildings', 'Buildings (ML)', 0], ['osm_buildings', 'Buildings (OSM)', 0], ['road_km', 'Road km', 1],
              ['main_road_km', 'Main road km', 1], ['masked_cells', 'Cells not scored', 0]].map(([k, label, d]) => (
              <tr key={k} className="border-b">
                <td className="py-1.5 pr-3 opacity-70">{label}</td>
                <td className="py-1.5 pr-3 tabular-nums">{fmt(c.facts[k].a, d)}</td>
                <td className="py-1.5 tabular-nums">{fmt(c.facts[k].b, d)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs opacity-60">Normalised values are percentiles across all of Chennai (GCC), so they compare directly between areas.</p>
      </div>
      <div className="order-1 h-64 shrink-0 md:order-2 md:h-auto md:w-[40%]">
        <MapView serviceArea={layers.serviceArea} stores={layers.stores} overlays={overlays} fit={fit} />
      </div>
    </div>
  )
}
