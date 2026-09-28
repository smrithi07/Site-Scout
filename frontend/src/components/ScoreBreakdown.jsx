// raw → normalised → weight → contribution for every factor: the whole answer to "how was this
// score reached?" (docs/DESIGN.md §5).
import ProvenanceBadge from './ProvenanceBadge'

export const fmt = (v, digits = 1) =>
  v == null ? '—' : Number(v).toLocaleString('en-IN', { maximumFractionDigits: digits })

function Bar({ value }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-16 overflow-hidden rounded bg-brand/10" aria-hidden>
        <div className="h-full bg-brand" style={{ width: `${value}%` }} />
      </div>
      <span className="tabular-nums">{fmt(value)}</span>
    </div>
  )
}

export default function ScoreBreakdown({ factors, score, missingFraction }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs uppercase tracking-wide opacity-60">
            <th className="py-2 pr-3 font-medium">Factor</th>
            <th className="py-2 pr-3 font-medium">Raw value</th>
            <th className="py-2 pr-3 font-medium">Normalised<br /><span className="normal-case">(0–100, vs Chennai)</span></th>
            <th className="py-2 pr-3 font-medium">Weight</th>
            <th className="py-2 font-medium text-right">Points</th>
          </tr>
        </thead>
        <tbody>
          {factors.map((f) => {
            const missing = f.normalized == null
            return (
              <tr key={f.factor} className={`border-b align-top ${missing ? 'opacity-60' : ''}`}>
                <td className="py-2 pr-3">
                  <div className="font-medium">{f.label}</div>
                  <div className="mt-0.5"><ProvenanceBadge value={f.provenance} /></div>
                  <div className="mt-1 max-w-xs text-xs opacity-70">{f.note}</div>
                </td>
                <td className="py-2 pr-3">
                  <span className="tabular-nums">{typeof f.raw === 'string' ? f.raw : fmt(f.raw, 0)}</span>
                  <div className="text-xs opacity-60">{f.unit}</div>
                  <div className="text-xs opacity-50">{f.source}</div>
                </td>
                <td className="py-2 pr-3">{missing ? <span className="text-red-700">not scored</span> : <Bar value={f.normalized} />}</td>
                <td className="py-2 pr-3 tabular-nums whitespace-nowrap">
                  {missing ? (
                    <span className="text-xs">{f.weight} → redistributed</span>
                  ) : (
                    <>
                      {fmt(f.effective_weight)}%
                      {Math.abs(f.effective_weight - f.weight) > 0.05 && <div className="text-xs opacity-60">configured {f.weight}%</div>}
                    </>
                  )}
                </td>
                <td className="py-2 text-right font-semibold tabular-nums">{missing ? '—' : fmt(f.contribution)}</td>
              </tr>
            )
          })}
        </tbody>
        {score != null && (
          <tfoot>
            <tr>
              <td colSpan={4} className="pt-2 text-right text-xs opacity-70">
                Score = sum of points{missingFraction > 0 ? ` (${Math.round(missingFraction * 100)}% of weight had no data and was redistributed)` : ''}
              </td>
              <td className="pt-2 text-right text-base font-bold tabular-nums">{fmt(score)}</td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  )
}
