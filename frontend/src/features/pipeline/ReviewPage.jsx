// BD Manager's property review (docs/DESIGN.md §6): the 30-second card up top, the next step
// (stage moves / follow-up) beside it, then the full evaluation breakdown, map, photos, notes,
// details and history. Allowed moves come from the API, so the stage rules live in one place.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import MapView from '../../components/MapView'
import ProvenanceBadge from '../../components/ProvenanceBadge'
import ScoreBreakdown, { fmt } from '../../components/ScoreBreakdown'
import { useMapLayers } from '../areas/AnalysePage'
import { pinOverlay } from '../scouting/mapLayers'
import { Card, OutcomeBadge, Photo, STAGE_LABEL } from '../scouting/shared'
import RequestStudyDialog from '../studies/RequestStudyDialog'
import StudyCard from '../studies/StudyCard'
import { FollowUpDialog, StageDialog } from './Dialogs'
import History from './History'

const MOVE_STYLE = {
  shortlisted: 'bg-brand text-white', approved: 'bg-emerald-700 text-white',
  rejected: 'border border-red-300 text-red-800', on_hold: 'border border-brand/30', under_review: 'border border-brand/30',
}
const RENT_TONE = { 'within band': 'text-emerald-800', 'below band': 'text-sky-800', 'above band': 'text-red-800' }
const SEVERITY = { high: 'bg-red-100 text-red-900', medium: 'bg-amber-100 text-amber-900', low: 'bg-stone-100 text-stone-700' }
const date = (at) => new Date(at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

function Risks({ risks }) {
  return (
    <ul className="space-y-1">
      {risks.map((x) => (
        <li key={x.rule_id} className="flex gap-2 text-sm">
          <span className={`h-fit rounded px-1.5 text-xs uppercase ${SEVERITY[x.severity]}`}>{x.severity}</span>
          <span>{x.message}</span>
        </li>
      ))}
    </ul>
  )
}

function QuickCard({ p }) {
  const r = p.review ?? {}
  const pending = p.evaluation_status === 'pending' && p.evaluation_job?.status !== 'failed'
  if (!r.outcome) {
    return (
      <Card title="At a glance">
        {pending ? <p className="animate-pulse text-sm">Evaluating…</p>
          : p.evaluation_job?.status === 'failed'
            ? <p className="text-sm text-red-700">Evaluation failed at {p.evaluation_job.error?.split(':')[0]}. <Link to={`/jobs/${p.evaluation_job.id}`} className="underline">Open the job to retry</Link></p>
            : <p className="text-sm">Not evaluated yet.</p>}
      </Card>
    )
  }
  const rent = r.rent_vs_band ?? {}
  return (
    <Card title="At a glance">
      <div className="flex flex-wrap items-center gap-2">
        <OutcomeBadge outcome={r.outcome} className="text-sm" />
        {r.score != null && <span className="text-2xl font-bold tabular-nums">{fmt(r.score)}<span className="text-sm font-normal opacity-60">/100</span></span>}
        {r.provisional && <span className="text-xs text-amber-800">provisional</span>}
        <span className="text-sm opacity-70">{r.confidence} confidence</span>
        {r.stale && <span className="animate-pulse text-xs text-amber-800">re-evaluating after an edit…</span>}
      </div>
      {r.outcome_reasons?.length > 0 && <p className="mt-1 text-sm">{r.outcome_reasons.join('; ')}</p>}
      {r.hard_flags?.length > 0 && (
        <ul className="mt-2 space-y-1">{r.hard_flags.map((f) => <li key={f.code} className="rounded bg-red-50 p-1.5 text-sm text-red-900">⚑ {f.message}</li>)}</ul>
      )}
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
        <dt className="opacity-60">Rent</dt>
        <dd>
          {rent.per_sqft != null
            ? <><b className={RENT_TONE[rent.position]}>₹{fmt(rent.per_sqft)}/sq ft · {rent.position}</b> <span className="opacity-70">(₹{rent.band.min}–{rent.band.max}, {rent.band.label})</span> <ProvenanceBadge value={rent.band.provenance} /></>
            : <span className="text-amber-800">not comparable — rent or area missing</span>}
        </dd>
        <dt className="opacity-60">Complete</dt>
        <dd>
          {r.completeness.complete_pct}% of fields
          {r.completeness.critical_missing.length > 0 && <span className="text-amber-800"> · missing {r.completeness.critical_missing.join(', ').replaceAll('_', ' ')}</span>}
        </dd>
        {p.status === 'possible_duplicate' && (
          <><dt className="opacity-60">Duplicate?</dt>
            <dd className="text-amber-800">possibly {p.duplicate_candidates.map((c) => <Link key={c.id} to={`/properties/${c.id}`} className="mr-1 underline">#{c.id}</Link>)}— the executive decides</dd></>
        )}
      </dl>
      {r.top_risks?.length > 0 && <div className="mt-3"><h3 className="mb-1 text-xs font-semibold uppercase opacity-60">Top risks</h3><Risks risks={r.top_risks} /></div>}
    </Card>
  )
}

function NextStep({ p, onMove, onFollowUp, onStudy }) {
  const { moves, follow_up: fu, study } = p.pipeline
  const open = (p.follow_ups ?? []).filter((f) => f.status === 'open')
  return (
    <Card title="Next step">
      {moves.length === 0 && <p className="text-sm opacity-70">{p.stage === 'approved' ? 'Approved — final.' : 'No manual moves from here.'}</p>}
      <div className="flex flex-wrap gap-2">
        {moves.map((to) => (
          <button key={to} onClick={() => onMove(to)} className={`rounded-md px-3 py-2 text-sm font-semibold ${MOVE_STYLE[to] ?? 'border'}`}>
            {to === 'under_review' && p.stage === 'rejected' ? 'Reopen'
              : to === 'under_review' && p.stage === 'needs_follow_up' ? 'Withdraw request' : STAGE_LABEL(to)}
          </button>
        ))}
        <button onClick={onFollowUp} disabled={!fu.allowed} title={fu.allowed ? '' : fu.why}
                className="rounded-md bg-accent px-3 py-2 text-sm font-semibold text-ink disabled:opacity-40">Ask executive…</button>
        {study.allowed && (
          <button onClick={onStudy} className="rounded-md bg-brand px-3 py-2 text-sm font-semibold text-white">Request study…</button>
        )}
      </div>
      {!fu.allowed && <p className="mt-1 text-xs opacity-60">Follow-up: {fu.why}</p>}
      {(p.follow_ups ?? []).length > 0 && (
        <div className="mt-3 border-t pt-2">
          <h3 className="mb-1 text-xs font-semibold uppercase opacity-60">Follow-ups {open.length > 0 && `(${open.length} open)`}</h3>
          <ul className="space-y-1.5 text-sm">
            {[...p.follow_ups].reverse().map((f) => (
              <li key={f.id}>
                <span className={`mr-1 rounded px-1 text-xs ${f.status === 'open' ? 'bg-accent' : 'bg-stone-100'}`}>{f.status}</span>
                <span className="opacity-70">{f.kind.replace('_', ' ')}:</span> {f.message}
                {f.response && <p className="ml-3 border-l-2 border-emerald-300 pl-2">↳ {f.response}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}

function Breakdown({ p }) {
  const [version, setVersion] = useState(null)       // null = latest
  const latest = p.evaluation
  const versions = useQuery({ queryKey: ['property', String(p.id), 'evaluations', latest?.version],
                              queryFn: () => api(`/properties/${p.id}/evaluations`), enabled: !!latest })
  const older = useQuery({ queryKey: ['property', String(p.id), 'evaluation', version],
                           queryFn: () => api(`/properties/${p.id}/evaluations/${version}`), enabled: version != null })
  const ev = version == null ? latest : older.data
  const [busy, setBusy] = useState(false)
  const queryClient = useQueryClient()
  const rerun = async () => {
    setBusy(true)
    try { await api(`/properties/${p.id}/evaluate`, { method: 'POST' }) } finally {
      setBusy(false); queryClient.invalidateQueries({ queryKey: ['property', String(p.id)] })
    }
  }
  if (!latest) return null
  return (
    <Card title="How the score was reached" action={
      <div className="flex items-center gap-2">
        {versions.data?.length > 1 && (
          <select value={version ?? ''} onChange={(e) => setVersion(e.target.value ? Number(e.target.value) : null)}
                  className="rounded border px-1 py-0.5 text-xs" aria-label="Evaluation version">
            {versions.data.map((v, i) => <option key={v.version} value={i === 0 ? '' : v.version}>v{v.version} · {v.outcome} · {v.trigger}{i === 0 ? ' (latest)' : ''}</option>)}
          </select>
        )}
        <button onClick={rerun} disabled={busy || p.evaluation_status === 'pending'} className="rounded border border-brand/30 px-2 py-0.5 text-xs disabled:opacity-40">Re-evaluate</button>
      </div>
    }>
      {!ev ? <p className="text-sm">Loading…</p> : (
        <>
          {version != null && <p className="mb-2 rounded bg-amber-50 p-1.5 text-xs text-amber-900">Showing v{ev.version} (older). Evaluations are never overwritten.</p>}
          <p className="mb-2 text-sm"><OutcomeBadge outcome={ev.outcome} /> <span className="ml-1 tabular-nums">{fmt(ev.score)}</span> · {ev.confidence} confidence</p>
          <ScoreBreakdown factors={ev.factors} score={ev.score} missingFraction={ev.completeness?.missing_weight_fraction} />
          {ev.risks.length > 0 && <div className="mt-3"><h3 className="mb-1 text-xs font-semibold uppercase opacity-60">All risks</h3><Risks risks={ev.risks} /></div>}
          <p className="mt-3 text-xs opacity-60">
            v{ev.version} of property version {ev.property_version} · data snapshot {ev.snapshot_id} · config {ev.config_version} · {date(ev.created_at)}
          </p>
        </>
      )}
    </Card>
  )
}

export default function ReviewPage() {
  const { id } = useParams()
  const queryClient = useQueryClient()
  const layers = useMapLayers({ withGrid: false })
  const [dialog, setDialog] = useState(null)          // {kind: 'move', to} | {kind: 'follow_up'}
  const [flash, setFlash] = useState(null)
  const [note, setNote] = useState('')

  const prop = useQuery({
    queryKey: ['property', id],
    queryFn: () => api(`/properties/${id}`),
    refetchInterval: (q) => (q.state.data?.evaluation_status === 'pending' && q.state.data?.evaluation_job?.status !== 'failed' ? 2000 : false),
  })
  const p = prop.data
  const history = useQuery({ queryKey: ['property', id, 'history', p?.version, p?.evaluation?.version, p?.notes?.length, p?.photos?.length],
                             queryFn: () => api(`/properties/${id}/history`), enabled: !!p })
  const overlays = useMemo(() => (p ? pinOverlay(p.lat, p.lon, p.gps_accuracy_m) : []), [p?.lat, p?.lon]) // eslint-disable-line react-hooks/exhaustive-deps
  const fit = useMemo(() => (p ? [[p.lon - 0.004, p.lat - 0.004], [p.lon + 0.004, p.lat + 0.004]] : null), [p?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['property', id] })
    queryClient.invalidateQueries({ queryKey: ['properties'] })
  }
  const done = (text) => { setDialog(null); setFlash(text); refresh() }

  if (prop.isError) return <p className="p-6 text-red-700">{prop.error.message}</p>
  if (!p) return <p className="p-6">Loading…</p>

  if (p.status === 'merged') {
    return (
      <div className="mx-auto max-w-xl space-y-3 p-4">
        <p className="text-xs text-brand">#{p.id} · merged</p>
        <h1 className="text-xl font-bold">{p.label}</h1>
        <Card tone="warn">Merged by the executive into <Link to={`/properties/${p.duplicate_of}`} className="font-semibold underline">#{p.duplicate_of}</Link> — review that property.</Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-6xl p-4">
      <Link to="/pipeline" className="text-sm text-brand">← Pipeline</Link>
      <div className="mt-1 mb-3 flex flex-wrap items-end gap-x-3 gap-y-1">
        <div>
          <p className="text-xs text-brand">#{p.id} · <span className="rounded bg-brand px-1.5 py-0.5 font-semibold text-white">{STAGE_LABEL(p.stage)}</span></p>
          <h1 className="text-xl font-bold">{p.label}</h1>
          <p className="text-xs opacity-70">
            {[p.locality, p.pincode, p.ward_no && `ward ${p.ward_no}`].filter(Boolean).join(' · ')}
            {' · '}onboarded by {p.created_by_name ?? 'unknown'} on {date(p.created_at)}
            {p.task_id && <> · <Link to={`/tasks/${p.task_id}`} className="underline">task #{p.task_id}</Link></>}
          </p>
        </div>
      </div>
      {flash && <div className="mb-3"><Card tone="ok"><p className="text-sm">✓ {flash}</p></Card></div>}

      <div className="grid gap-3 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="min-w-0 space-y-3">
          <QuickCard p={p} />
          <NextStep p={p} onMove={(to) => setDialog({ kind: 'move', to })} onFollowUp={() => setDialog({ kind: 'follow_up' })}
                    onStudy={() => setDialog({ kind: 'study' })} />
          <StudyCard propertyId={p.id} onChanged={refresh} />
          <Breakdown p={p} />
        </div>
        <div className="min-w-0 space-y-3">
          <div className="h-56 overflow-hidden rounded-lg"><MapView serviceArea={layers.serviceArea} stores={layers.stores} overlays={overlays} fit={fit} /></div>
          <Card title={`Photos (${p.photos.length})`}>
            {p.photos.length === 0 ? <p className="text-sm text-amber-800">None yet — ask the executive for photos.</p>
              : <div className="flex flex-wrap gap-2">{p.photos.map((ph) => <Photo key={ph.id} propertyId={p.id} photo={ph} />)}</div>}
          </Card>
          <Card title="Details">
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
              {[['Rent', p.monthly_rent != null && `₹${fmt(p.monthly_rent, 0)} ${p.rent_unit?.replaceAll('_', ' ')}`], ['Area', p.area_sqft && `${fmt(p.area_sqft, 0)} sq ft`],
                ['Deposit', p.security_deposit != null && `₹${fmt(p.security_deposit, 0)}`], ['Available', p.availability],
                ['Frontage', p.frontage_ft && `${p.frontage_ft} ft`], ['Road width', p.road_width_ft && `${p.road_width_ft} ft`], ['Floor', p.floor],
                ['Visibility', p.visibility], ['Access', p.accessibility], ['Parking', p.parking], ['Condition', p.condition],
                ['Owner', p.owner_name], ['Phone', p.owner_phone], ['Address', p.address], ['Landmark', p.landmark],
                ['Nearby road', p.nearby_road], ['GPS', p.gps_accuracy_m != null && `±${fmt(p.gps_accuracy_m, 0)} m`]]
                .filter(([, v]) => v).map(([k, v]) => <div key={k} className="contents"><dt className="opacity-60">{k}</dt><dd>{v}</dd></div>)}
            </dl>
          </Card>
          <Card title="Notes">
            <ul className="space-y-1 text-sm">{p.notes.map((n) => <li key={n.id}><span className="text-xs uppercase opacity-50">{n.kind.replace('_', ' ')}</span> {n.text}</li>)}</ul>
            <form onSubmit={async (e) => { e.preventDefault(); await api(`/properties/${p.id}/notes`, { method: 'POST', body: { text: note } }); setNote(''); refresh() }}
                  className="mt-2 flex gap-2">
              <input value={note} onChange={(e) => setNote(e.target.value)} required placeholder="Add a note" className="min-w-0 flex-1 rounded border px-2 py-1.5 text-sm" />
              <button className="rounded border border-brand px-3 text-sm text-brand">Add</button>
            </form>
          </Card>
          <Card title="History"><History events={history.data} /></Card>
        </div>
      </div>

      {dialog?.kind === 'move' && (
        <StageDialog property={p} to={dialog.to} onClose={() => setDialog(null)} onStale={() => prop.refetch()}
                     onDone={(updated) => { queryClient.setQueryData(['property', id], updated); done(`Moved to ${STAGE_LABEL(updated.stage)}.`) }} />
      )}
      {dialog?.kind === 'study' && (
        <RequestStudyDialog property={p} onClose={() => setDialog(null)} onStale={() => prop.refetch()}
                            onDone={(study) => { queryClient.invalidateQueries({ queryKey: ['studies'] }); done(`Study #${study.id} requested — ${study.survey.segments} lanes to survey. The Survey Manager plans it next.`) }} />
      )}
      {dialog?.kind === 'follow_up' && (
        <FollowUpDialog property={p} onClose={() => setDialog(null)} onStale={() => prop.refetch()}
                        onDone={() => done(`Asked ${p.pipeline.follow_up.assignee}. The property waits in “needs follow up” until they answer.`)} />
      )}
    </div>
  )
}
