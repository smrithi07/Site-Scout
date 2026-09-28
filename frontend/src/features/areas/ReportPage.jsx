// Phase 5a placeholder: proves the run → report hand-off. The full report view is Phase 5b.
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'

export default function ReportPage() {
  const { id } = useParams()
  const report = useQuery({ queryKey: ['report', id], queryFn: () => api(`/areas/reports/${id}`) })
  if (report.isError) return <p className="p-6 text-red-700">{report.error.message}</p>
  if (!report.data) return <p className="p-6">Loading…</p>
  const r = report.data
  return (
    <div className="mx-auto max-w-3xl p-6">
      <p className="text-sm text-brand">Area Fitness Report · v{r.version}</p>
      <h1 className="text-2xl font-bold">{r.label}</h1>
      <p className="mt-2 text-lg">
        {r.score != null ? <><strong>{r.score}</strong>/100 · {r.rating} · {r.confidence} confidence</> : r.status.replace('_', ' ')}
      </p>
      <p className="mt-4">{r.narrative.summary}</p>
      <p className="mt-6 text-sm opacity-70">Full report view (factor breakdown, hotspot map, compare) arrives in Phase 5b.</p>
      <Link to="/areas/analyse" className="mt-4 inline-block text-brand underline">Analyse another area</Link>
    </div>
  )
}
