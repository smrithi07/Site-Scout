// The Catchment Summary (docs/DESIGN.md §7 Roll-up): what the survey found, over surveyed lanes
// only, with where each number came from, how confident it is and why. Scores use UNCALIBRATED
// thresholds and are hidden entirely below the coverage floor (facts only).
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import ProvenanceBadge from '../../components/ProvenanceBadge'
import { fmt } from '../../components/ScoreBreakdown'
import { Card } from '../scouting/shared'

const SIGNALS = [
  ['residential', 'Residential density'], ['commercial', 'Commercial density'], ['footfall', 'Observed footfall'],
  ['accessibility', 'Accessibility'], ['parking', 'Parking'], ['competition', 'Competition (observed)'],
]
const CONF = { high: 'bg-emerald-100 text-emerald-900', medium: 'bg-sky-100 text-sky-900', low: 'bg-amber-100 text-amber-900' }
const ANCHOR = { school: 'School', hospital: 'Hospital', transit: 'Bus / rail', office: 'Office', market: 'Market', temple: 'Place of worship', other: 'Other' }

function Bar({ value }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-16 overflow-hidden rounded bg-brand/10"><div className="h-full bg-brand" style={{ width: `${value}%` }} /></div>
      <span className="text-xs tabular-nums">{fmt(value, 0)}</span>
    </div>
  )
}

/** Job state while the roll-up runs (or failed): shown instead of the summary until it exists. */
export function RollupStatus({ study }) {
  const j = study.rollup_job
  if (!j || j.status === 'succeeded') return null
  if (j.status === 'failed') {
    return <Card tone="bad"><p className="text-sm">Roll-up failed at {j.error?.split(':')[0]}. Captured data is safe. <Link to={`/jobs/${j.id}`} className="underline">Open the job to retry</Link></p></Card>
  }
  return <Card><p className="animate-pulse text-sm">Rolling up the lane data into the Catchment Summary… <Link to={`/jobs/${j.id}`} className="underline">progress</Link></p></Card>
}

export default function SummaryCard({ studyId }) {
  const [version, setVersion] = useState(null)
  const q = useQuery({ queryKey: ['summary', studyId, version], queryFn: () => api(`/studies/${studyId}/summary${version ? `?version=${version}` : ''}`) })
  const s = q.data
  if (q.isError) return null
  if (!s) return <Card><p className="text-sm">Loading summary…</p></Card>
  const c = s.coverage
  const pct = (m) => (c.total_length_m ? (100 * m) / c.total_length_m : 0)

  return (
    <Card title={<>Catchment Summary <span className="font-normal opacity-60">v{s.version}</span></>} action={
      s.versions.length > 1 && (
        <select value={version ?? ''} onChange={(e) => setVersion(e.target.value ? Number(e.target.value) : null)} className="rounded border px-1 py-0.5 text-xs" aria-label="Summary version">
          {s.versions.map((v, i) => <option key={v} value={i === 0 ? '' : v}>v{v}{i === 0 ? ' (latest)' : ''}</option>)}
        </select>
      )}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-sm font-semibold ${CONF[s.confidence]}`}>{s.confidence} confidence</span>
        {s.facts_only && <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">facts only — coverage too low to score</span>}
        <span className="text-xs opacity-60">{s.trigger.replaceAll('_', ' ')} · config {s.config_version}</span>
      </div>
      <ul className="mt-1 list-disc pl-5 text-xs opacity-80">{s.confidence_reasons.map((r) => <li key={r}>{r}</li>)}</ul>

      <div className="mt-3">
        <div className="flex h-2.5 overflow-hidden rounded-full bg-stone-200" aria-label="coverage">
          <div className="bg-emerald-600" style={{ width: `${pct(c.surveyed_length_m)}%` }} title="surveyed" />
          <div className="bg-amber-500" style={{ width: `${pct(c.gap_length_m)}%` }} title="could not survey" />
        </div>
        <p className="mt-1 text-xs">
          <b>{fmt(c.surveyed_length_m / 1000, 1)} km surveyed</b> of {fmt(c.total_length_m / 1000, 1)} km ({Math.round(c.surveyed_share * 100)}%, {c.surveyed_lanes} lanes)
          {c.gap_lanes > 0 && ` · ${c.gap_lanes} could not survey`} · {fmt(c.not_surveyed_length_m / 1000, 1)} km not surveyed (never filled in)
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-1 text-xs">
          Sources: {Object.entries(c.sources).filter(([, v]) => v > 0).map(([k, v]) => (
            <span key={k} className="inline-flex items-center gap-1"><ProvenanceBadge value={k} /> {Math.round(v * 100)}%</span>
          ))}
        </p>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b text-left text-xs uppercase opacity-60">
            <th className="py-1 pr-2 font-medium">Signal</th><th className="pr-2 font-medium">Observed</th><th className="font-medium">Score</th>
          </tr></thead>
          <tbody>
            {SIGNALS.map(([k, label]) => {
              const x = s.signals[k]
              return (
                <tr key={k} className="border-b align-top last:border-0">
                  <td className="py-1.5 pr-2"><div className="font-medium">{label}</div><ProvenanceBadge value={x.provenance} /></td>
                  <td className="py-1.5 pr-2">
                    <span className="tabular-nums">{x.value == null ? '—' : fmt(x.value, 1)}</span> <span className="text-xs opacity-60">{x.unit}</span>
                    {k === 'footfall' && x.time_bands && (
                      <div className="mt-0.5 flex flex-wrap gap-1 text-[11px]">{Object.entries(x.time_bands).map(([b, v]) => <span key={b} className="rounded bg-stone-100 px-1">{b} {Math.round(v * 100)}%</span>)}</div>
                    )}
                    {k === 'accessibility' && x.share_poor != null && <div className="text-xs opacity-70">{Math.round(x.share_poor * 100)}% of length rated poor access</div>}
                    {k === 'parking' && x.share_with_parking != null && <div className="text-xs opacity-70">{Math.round(x.share_with_parking * 100)}% of length has some parking</div>}
                    {x.notes.map((n) => <div key={n} className={`text-xs ${x.single_band ? 'text-amber-800' : 'opacity-70'}`}>{n}</div>)}
                  </td>
                  <td className="py-1.5">{x.normalized == null ? <span className="text-xs opacity-60">{s.facts_only ? 'facts only' : '—'}</span> : <Bar value={x.normalized} />}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {s.anchors.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-semibold uppercase opacity-60">Anchors ({s.anchors.length}, de-duplicated)</p>
          <p className="flex flex-wrap gap-1 text-sm">{Object.entries(s.anchors.reduce((acc, a) => {
            const k = `${ANCHOR[a.type] ?? a.type}${a.name ? `: ${a.name}` : ''}`
            acc[k] = (acc[k] ?? 0) + 1
            return acc
          }, {})).map(([k, n]) => <span key={k} className="rounded bg-stone-100 px-1.5 whitespace-nowrap">{k}{n > 1 && ` ×${n}`}</span>)}</p>
        </div>
      )}
      <p className="mt-2 text-[11px] opacity-60">Scores use uncalibrated thresholds (config {s.config_version}); computed over surveyed lanes only. The raw numbers are what was observed.</p>
    </Card>
  )
}
