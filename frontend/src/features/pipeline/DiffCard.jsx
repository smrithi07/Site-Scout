// "Why did the score change?" (docs/DESIGN.md §7 v1 → v2): the diff computed by code — every
// factor change with its cause, the points it moved, and whether they add up — plus the narrative
// that only phrases it (with who wrote it). The classification is what keeps this from being a
// wall of numbers.
import { fmt } from '../../components/ScoreBreakdown'
import NarrativeSource from '../areas/NarrativeSource'
import { Card, OutcomeBadge } from '../scouting/shared'

export const CAUSE = {
  'factor newly included': { label: 'newly included', style: 'bg-emerald-100 text-emerald-900' },
  'data change': { label: 'data change', style: 'bg-sky-100 text-sky-900' },
  'config change': { label: 'config change', style: 'bg-violet-100 text-violet-900' },
  renormalization: { label: 'renormalization', style: 'bg-stone-200 text-stone-800' },
  'factor dropped': { label: 'dropped', style: 'bg-amber-100 text-amber-900' },
}

const signed = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${fmt(v)}`)

export default function DiffCard({ ev }) {
  const d = ev.diff
  if (!d) return null
  const n = ev.narrative
  return (
    <Card title={`What changed: v${d.from_version} → v${d.to_version}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="tabular-nums">{fmt(d.score.before)}</span><OutcomeBadge outcome={d.outcome.before} />
        <span aria-hidden>→</span>
        <span className="font-semibold tabular-nums">{fmt(d.score.after)}</span><OutcomeBadge outcome={d.outcome.after} />
        <span className={`rounded px-1.5 text-sm font-semibold tabular-nums ${d.score.change > 0 ? 'bg-emerald-100 text-emerald-900' : d.score.change < 0 ? 'bg-red-100 text-red-900' : 'bg-stone-100'}`}>
          {signed(d.score.change)} points
        </span>
        <span className="text-xs opacity-70">confidence {d.confidence.before} → {d.confidence.after}</span>
      </div>
      {d.study && <p className="mt-1 text-xs opacity-70">Triggered by catchment study #{d.study.study_id} (summary v{d.study.summary_version}, {d.study.confidence} confidence{d.study.facts_only ? ', facts only' : ''}).</p>}
      {d.factors.some((c) => c.after?.source?.startsWith('Catchment study') && !c.before?.source?.startsWith('Catchment study')) && (
        <p className="mt-2 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
          <b>Not like-for-like:</b> the estimates were ranked against all of Chennai; the study's observed values are scored on
          uncalibrated thresholds. For factors that switched source, read the observed facts below, not only the points.
        </p>
      )}

      {n && (
        <div className="mt-3 rounded-md bg-brand-light/60 p-2.5">
          <p className="text-sm font-medium">{n.summary}</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">{n.changes.map((c) => <li key={c}>{c}</li>)}</ul>
          <div className="mt-2"><NarrativeSource source={ev.narrative_source} meta={ev.narrative_meta ?? {}} /></div>
        </div>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b text-left text-xs uppercase opacity-60">
            <th className="py-1 pr-2 font-medium">Factor</th><th className="pr-2 font-medium">Why</th>
            <th className="pr-2 font-medium">Normalised</th><th className="pr-2 font-medium">Weight</th><th className="text-right font-medium">Points</th>
          </tr></thead>
          <tbody>
            {d.factors.map((c) => (
              <tr key={c.factor} className="border-b align-top last:border-0">
                <td className="py-1.5 pr-2 font-medium">{c.label}</td>
                <td className="py-1.5 pr-2">
                  <span className={`rounded px-1.5 py-0.5 text-xs whitespace-nowrap ${CAUSE[c.cause]?.style}`}>{CAUSE[c.cause]?.label ?? c.cause}</span>
                  {c.causes.length > 1 && <span className="ml-1 text-[11px] opacity-60">+ {c.causes.filter((x) => x !== c.cause).map((x) => CAUSE[x]?.label ?? x).join(', ')}</span>}
                  <p className="mt-0.5 text-xs opacity-75">{c.explanation}</p>
                </td>
                <td className="py-1.5 pr-2 whitespace-nowrap tabular-nums">{fmt(c.before?.normalized)} → {fmt(c.after?.normalized)}</td>
                <td className="py-1.5 pr-2 whitespace-nowrap tabular-nums">{fmt(c.before?.effective_weight)}% → {fmt(c.after?.effective_weight)}%</td>
                <td className={`py-1.5 text-right font-semibold tabular-nums ${c.points_change > 0 ? 'text-emerald-800' : c.points_change < 0 ? 'text-red-800' : ''}`}>{signed(c.points_change)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr><td colSpan={4} className="pt-1.5 text-right text-xs opacity-70">
            Factor changes add up to {signed(d.score.explained_by_factors)}{Math.abs(d.score.rounding_gap ?? 0) >= 0.1 && ` (rounding ${signed(d.score.rounding_gap)})`}
          </td><td className="pt-1.5 text-right font-bold tabular-nums">{signed(d.score.change)}</td></tr></tfoot>
        </table>
      </div>

      {d.new_facts.length > 0 && (
        <div className="mt-3"><h3 className="text-xs font-semibold uppercase opacity-60">Newly observed</h3>
          <ul className="list-disc pl-5 text-sm">{d.new_facts.map((f) => <li key={f.fact}>{f.text}</li>)}</ul></div>
      )}
      {(d.new_risks.length > 0 || d.resolved_risks.length > 0) && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {d.new_risks.length > 0 && <div><h3 className="text-xs font-semibold uppercase text-red-800">New risks</h3>
            <ul className="list-disc pl-5 text-sm">{d.new_risks.map((r) => <li key={r.rule_id}>{r.message}</li>)}</ul></div>}
          {d.resolved_risks.length > 0 && <div><h3 className="text-xs font-semibold uppercase text-emerald-800">No longer flagged</h3>
            <ul className="list-disc pl-5 text-sm opacity-80">{d.resolved_risks.map((r) => <li key={r.rule_id}>{r.message}</li>)}</ul></div>}
        </div>
      )}
      {d.config.before !== d.config.after && <p className="mt-2 text-xs opacity-60">Config {d.config.before} → {d.config.after}.</p>}
    </Card>
  )
}
