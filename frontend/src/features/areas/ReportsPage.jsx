// Saved Area Fitness Reports: newest first, grouped by area with their versions; tick two to compare.
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { fmt } from '../../components/ScoreBreakdown'

const when = (iso) => new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export default function ReportsPage() {
  const navigate = useNavigate()
  const [picked, setPicked] = useState([])
  const [filter, setFilter] = useState('')
  const reports = useQuery({ queryKey: ['reports', 'all'], queryFn: () => api('/areas/reports?limit=200') })

  const groups = useMemo(() => {
    const byArea = new Map()
    for (const r of reports.data ?? []) {
      if (filter && !r.label.toLowerCase().includes(filter.toLowerCase())) continue
      if (!byArea.has(r.area_key)) byArea.set(r.area_key, [])
      byArea.get(r.area_key).push(r)
    }
    return [...byArea.values()]
  }, [reports.data, filter])

  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2)))

  return (
    <div className="mx-auto max-w-4xl p-4 md:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold">Area reports</h1>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by name"
          className="rounded border px-2 py-1 text-sm"
          aria-label="Filter reports"
        />
        <button
          disabled={picked.length !== 2}
          onClick={() => navigate(`/areas/compare/${picked[0]}/${picked[1]}`)}
          className="ml-auto rounded-md bg-accent px-4 py-2 text-sm font-semibold text-ink shadow enabled:hover:brightness-95 disabled:opacity-40"
        >
          Compare {picked.length}/2 selected
        </button>
      </div>
      <p className="mt-1 text-sm opacity-70">Tick any two reports — two versions of one area, or two different areas.</p>

      {reports.isError && <p className="mt-4 text-red-700">{reports.error.message}</p>}
      {reports.data?.length === 0 && (
        <p className="mt-6">No reports yet. <Link to="/areas/analyse" className="text-brand underline">Analyse an area</Link>.</p>
      )}
      <ul className="mt-4 space-y-3">
        {groups.map((versions) => (
          <li key={versions[0].area_key} className="rounded-lg border border-brand/15 bg-white">
            <div className="border-b border-brand/10 px-3 py-2 font-semibold">{versions[0].label}</div>
            <table className="w-full text-sm">
              <tbody>
                {versions.map((r) => (
                  <tr key={r.id} className="border-b border-brand/5 last:border-0">
                    <td className="w-8 py-1.5 pl-3">
                      <input type="checkbox" checked={picked.includes(r.id)} onChange={() => toggle(r.id)} aria-label={`Select ${r.label} v${r.version}`} />
                    </td>
                    <td className="py-1.5">v{r.version}</td>
                    <td className="py-1.5 opacity-70">{when(r.created_at)}</td>
                    <td className="py-1.5 font-semibold tabular-nums">{r.score != null ? fmt(r.score) : '—'}</td>
                    <td className="py-1.5">{r.rating ?? r.status.replace('_', ' ')}</td>
                    <td className="hidden py-1.5 text-xs opacity-60 sm:table-cell">{r.narrative_source}</td>
                    <td className="py-1.5 pr-3 text-right"><Link to={`/areas/reports/${r.id}`} className="text-brand underline">open</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </li>
        ))}
      </ul>
    </div>
  )
}
