// BD Manager's view of a property's catchment study: status only (docs/DESIGN.md §4) — coverage,
// the reuse decisions with their reasons, unit progress — and the option to cancel it.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import { fmt } from '../../components/ScoreBreakdown'
import { Card } from '../scouting/shared'
import { CoverageBar, MODES, StatusBadge } from './reuse'
import SummaryCard, { RollupStatus } from './SummaryCard'

const OPEN = ['requested', 'planned', 'in_progress']

export default function StudyCard({ propertyId, onChanged }) {
  const queryClient = useQueryClient()
  const list = useQuery({ queryKey: ['studies', { property: propertyId }], queryFn: () => api(`/studies?property_id=${propertyId}`),
                         refetchInterval: (q) => (['queued', 'running'].includes(q.state.data?.[0]?.rollup_job?.status) ? 2000 : false) })
  const [cancelling, setCancelling] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState(null)
  const s = list.data?.[0]
  if (!s) return null
  const open = OPEN.includes(s.status)

  const cancel = async (e) => {
    e.preventDefault(); setError(null)
    try {
      await api(`/studies/${s.id}/cancel`, { method: 'POST', body: { version: s.version, reason } })
      setCancelling(false); setReason('')
      queryClient.invalidateQueries({ queryKey: ['studies'] }); onChanged?.()
    } catch (err) {
      setError(err.status === 409 ? `${err.message} — reloaded.` : err.message)
      list.refetch()
    }
  }

  return (
    <>
    <Card title={<>Catchment study #{s.id} <StatusBadge status={s.status} /></>}>
      <CoverageBar reuse={s.reuse} compact />
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="opacity-60">Requested</dt>
        <dd>{MODES[s.requested_mode].label}{s.request_reason && <span className="opacity-70"> — “{s.request_reason}”</span>}</dd>
        {s.planned_mode && (<>
          <dt className="opacity-60">Planned</dt>
          <dd>{MODES[s.planned_mode].label}{s.plan_reason && <span className="opacity-70"> — “{s.plan_reason}”</span>}
            {s.planned_mode !== s.requested_mode && <span className="ml-1 rounded bg-amber-100 px-1 text-xs text-amber-900">changed by the Survey Manager</span>}</dd>
        </>)}
        <dt className="opacity-60">To survey</dt>
        <dd>{s.survey.segments} lanes · {fmt(s.survey.length_m / 1000, 1)} km</dd>
        {s.units.count > 0 && (<>
          <dt className="opacity-60">Units</dt>
          <dd>{s.units.count} ({s.units.assigned} assigned) · {fmt(s.units.total_minutes / 60, 1)} h of fieldwork</dd>
        </>)}
        {s.status === 'cancelled' && (<><dt className="opacity-60">Cancelled</dt><dd>“{s.cancel_reason}”</dd></>)}
      </dl>
      {open && !cancelling && <button onClick={() => setCancelling(true)} className="mt-2 text-xs text-red-800 underline">Cancel this study…</button>}
      {cancelling && (
        <form onSubmit={cancel} className="mt-2 flex gap-2">
          <input autoFocus required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why cancel? (the property returns to shortlisted)"
                 className="min-w-0 flex-1 rounded border px-2 py-1.5 text-sm" />
          <button className="rounded border border-red-300 px-3 text-sm text-red-800">Cancel study</button>
        </form>
      )}
      {error && <p className="mt-1 text-sm text-red-800">{error}</p>}
    </Card>
    <RollupStatus study={s} />
    {s.summary && <SummaryCard key={s.summary.id} studyId={s.id} />}
    </>
  )
}
