// Area Fitness Report (M1): verdict, how it was reached, where to scout, and the facts behind it.
// Everything shown comes from the saved, immutable report version.
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import MapView, { boundsOf } from '../../components/MapView'
import ScoreBreakdown, { fmt } from '../../components/ScoreBreakdown'
import { useMapLayers } from './AnalysePage'
import NarrativeSource from './NarrativeSource'
import { reportOverlays } from './reportLayers'

const STATUS_TEXT = { facts_only: 'Facts only — no rating', insufficient_data: 'Insufficient data — no rating' }
const MASK_LABELS = { industrial: 'industrial', water: 'water', wetland: 'wetland', sea: 'sea', beach: 'beach',
                      aeroway: 'airport', military: 'military', empty: 'empty land' }

const date = (iso) => (iso ? new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—')
const dateTime = (iso) => new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

function Section({ title, children, aside }) {
  return (
    <section className="mt-6">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-wide text-brand uppercase">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  )
}

export default function ReportPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const layers = useMapLayers()
  const [focus, setFocus] = useState(null)
  const [runError, setRunError] = useState(null)
  const report = useQuery({ queryKey: ['report', id], queryFn: () => api(`/areas/reports/${id}`) })
  const history = useQuery({
    queryKey: ['reports', report.data?.area_key],
    queryFn: () => api(`/areas/reports?area_key=${report.data.area_key}`),
    enabled: !!report.data,
  })
  const users = useQuery({ queryKey: ['demo-users'], queryFn: () => api('/auth/demo-users', { token: '' }) })

  const r = report.data
  const overlays = useMemo(() => (r ? reportOverlays(r) : []), [r])
  const fit = useMemo(() => {
    if (focus) return [[focus.lon - 0.006, focus.lat - 0.006], [focus.lon + 0.006, focus.lat + 0.006]]
    return r ? boundsOf(r.cells_geojson) : null
  }, [r, focus])

  if (report.isError) return <p className="p-6 text-red-700">{report.error.message}</p>
  if (!r) return <p className="p-6">Loading report…</p>

  const area = r.result.area
  const facts = r.result.facts
  const hotspots = r.result.hotspots
  const author = users.data?.find((u) => u.id === r.created_by)?.name ?? 'system'
  const others = (history.data ?? []).filter((h) => h.id !== r.id)

  const runAgain = async () => {
    setRunError(null)
    try {
      const res = await api('/areas/reports', { method: 'POST', body: r.selection })
      navigate(`/jobs/${res.job_id}`)
    } catch (e) {
      setRunError(e.message)
    }
  }

  return (
    <div className="flex h-full flex-col md:flex-row">
      <article className="order-2 min-h-0 flex-1 overflow-y-auto p-4 md:order-1 md:p-6">
        {/* Header */}
        <p className="text-sm text-brand">
          Area Fitness Report · v{r.version}
          {r.version < r.latest_version && <span className="ml-2 rounded bg-amber-100 px-1.5 text-amber-900">newer version exists (v{r.latest_version})</span>}
        </p>
        <h1 className="text-2xl font-bold">{r.label}</h1>
        <p className="mt-1 text-xs opacity-70">
          {dateTime(r.created_at)} · by {author} · {r.resolved.area_km2} km² · boundary: {r.resolved.basis.label}
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-4 rounded-xl border border-brand/20 bg-white p-4">
          {r.status === 'scored' ? (
            <>
              <div>
                <div className="text-4xl font-bold text-brand tabular-nums">{fmt(r.score)}</div>
                <div className="text-xs opacity-60">out of 100</div>
              </div>
              <div>
                <div className="text-lg font-semibold">{r.rating}</div>
                <div className="text-sm">{r.confidence} confidence</div>
              </div>
            </>
          ) : (
            <div>
              <div className="text-lg font-semibold text-amber-800">{STATUS_TEXT[r.status]}</div>
              <p className="text-sm">{area.reason}</p>
            </div>
          )}
          <dl className="ml-auto grid grid-cols-[auto_auto] gap-x-3 text-xs">
            <dt className="opacity-60">Data as of</dt><dd>OSM {date(facts.data_as_of.osm_retrieved)}</dd>
            <dt className="opacity-60">Stores</dt><dd>{date(facts.data_as_of.stores_fetched)}</dd>
            <dt className="opacity-60">Snapshot</dt><dd>#{r.snapshot_id} · config {r.config_version}</dd>
          </dl>
        </div>
        {r.resolved.warnings?.map((w) => <p key={w} className="mt-2 text-sm text-amber-800">⚠ {w}</p>)}

        {/* Narrative */}
        <Section title="Summary" aside={null}>
          <NarrativeSource source={r.narrative_source} meta={r.result.narrative_meta} />
          <p className="mt-2 text-base">{r.narrative.summary}</p>
          {r.narrative.why.length > 0 && (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{r.narrative.why.map((w) => <li key={w}>{w}</li>)}</ul>
          )}
        </Section>

        {/* How the score was reached */}
        {area.factors.length > 0 && (
          <Section title="How the score was reached">
            <ScoreBreakdown factors={area.factors} score={r.score} missingFraction={area.missing_weight_fraction} />
          </Section>
        )}

        {/* Where to scout */}
        <Section title="Where to scout first" aside={focus && <button onClick={() => setFocus(null)} className="text-xs text-brand underline">show whole area</button>}>
          {hotspots.length === 0 ? (
            <p className="text-sm opacity-70">No hotspots — no part of this area has enough data to score.</p>
          ) : (
            <ol className="space-y-2">
              {hotspots.map((h, i) => (
                <li key={h.h3}>
                  <button
                    onClick={() => setFocus(h)}
                    className={`w-full rounded-lg border bg-white p-3 text-left text-sm hover:border-brand ${focus?.h3 === h.h3 ? 'border-brand' : 'border-brand/15'}`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-xs font-bold text-ink">{i + 1}</span>
                      <span className="font-semibold">Ward {h.ward_no}</span>
                      <span className="ml-auto tabular-nums">score {fmt(h.score)}</span>
                    </div>
                    <div className="mt-1 opacity-80">
                      {h.reasons.map((x) => `${x.label} ${fmt(x.normalized, 0)}/100`).join(' · ')}
                    </div>
                    <div className="mt-0.5 text-xs opacity-60">
                      {fmt(h.facts.ml_buildings, 0)} buildings · {h.facts.competitors_in_cell} grocery shops in cell ·
                      nearest Savomart {h.facts.nearest_store_m != null ? `${fmt(h.facts.nearest_store_m / 1000)} km` : '—'}
                    </div>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </Section>

        {/* Facts */}
        <Section title="What's there">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <div><dt className="opacity-60">Buildings</dt><dd>{fmt(facts.ml_buildings, 0)} (ML footprints) · {fmt(facts.osm_buildings, 0)} mapped in OSM</dd></div>
            <div>
              <dt className="opacity-60">Grocery competitors (OSM, lower bound)</dt>
              <dd>{facts.competitors.count}{facts.competitors.examples.length > 0 && <span className="opacity-70"> — {facts.competitors.examples.slice(0, 5).join(', ')}</span>}</dd>
            </div>
            <div>
              <dt className="opacity-60">Footfall anchors</dt>
              <dd>{Object.entries(facts.anchors).map(([k, v]) => `${v.count} ${k}`).join(' · ')}</dd>
            </div>
            <div><dt className="opacity-60">Roads</dt><dd>{fmt(facts.road_km)} km ({fmt(facts.main_road_km)} km main roads)</dd></div>
            <div>
              <dt className="opacity-60">Savomart</dt>
              <dd>
                {facts.savomart_stores_inside.length > 0 && <>{facts.savomart_stores_inside.map((s) => s.name).join(', ')} inside · </>}
                nearest: {facts.nearest_savomart ? `${facts.nearest_savomart.name}, ${fmt(facts.nearest_savomart.distance_m / 1000)} km` : '—'}
              </dd>
            </div>
            <div><dt className="opacity-60">Wards · zones · pincodes</dt><dd>{facts.wards.join(', ')} · {facts.zones.join(', ')} · {facts.pincodes.join(', ')}</dd></div>
            {facts.masked_cells > 0 && (
              <div className="sm:col-span-2">
                <dt className="opacity-60">Not scored</dt>
                <dd>{Object.entries(facts.masked_by).map(([k, n]) => `${n} cells ${MASK_LABELS[k] ?? k}`).join(' · ')} (shown on the map, excluded from averages)</dd>
              </div>
            )}
          </dl>
        </Section>

        <Section title="Caveats">
          <ul className="list-disc space-y-1 pl-5 text-sm opacity-80">{r.narrative.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
        </Section>

        {/* Versions */}
        <Section title="Versions of this area">
          <ul className="space-y-1 text-sm">
            {(history.data ?? []).map((h) => (
              <li key={h.id} className="flex flex-wrap items-center gap-2">
                <span className={h.id === r.id ? 'font-semibold' : ''}>v{h.version}</span>
                <span className="opacity-70">{dateTime(h.created_at)}</span>
                <span className="tabular-nums">{h.score != null ? fmt(h.score) : h.status.replace('_', ' ')}</span>
                {h.id === r.id ? <span className="text-xs opacity-60">(this report)</span> : (
                  <>
                    <Link to={`/areas/reports/${h.id}`} className="text-brand underline">open</Link>
                    <Link to={`/areas/compare/${h.id}/${r.id}`} className="text-brand underline">compare with this</Link>
                  </>
                )}
              </li>
            ))}
          </ul>
          <div className="mt-3 flex flex-wrap gap-2">
            <button onClick={runAgain} className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-ink shadow hover:brightness-95">
              Run again (new version)
            </button>
            {others.length === 0 && <Link to="/areas/reports" className="rounded-md border border-brand/30 px-4 py-2 text-sm text-brand">Compare with another area</Link>}
          </div>
          {runError && <p className="mt-2 text-sm text-red-700">{runError}</p>}
        </Section>
      </article>
      <div className="order-1 h-72 shrink-0 md:order-2 md:h-auto md:w-[45%]">
        <MapView serviceArea={layers.serviceArea} stores={layers.stores} overlays={overlays} fit={fit} />
      </div>
    </div>
  )
}
