// Survey Manager: one catchment study. Where it is (property without commercial fields), what
// existing data covers (map + coverage), the final reuse decision (which generates the units), and
// the unit planner: lanes selected on the map → move / split / merge, assignment, progress.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import MapView, { boundsOf } from '../../components/MapView'
import { fmt } from '../../components/ScoreBreakdown'
import { useMapLayers } from '../areas/AnalysePage'
import { isStale } from '../pipeline/Dialogs'
import { Card } from '../scouting/shared'
import { CoverageBar, MODES, STATE, STATE_ORDER, StatusBadge, catchmentOverlays, circle, reasonNeeded, unitColor, unitOverlays } from './reuse'
import SummaryCard, { RollupStatus } from './SummaryCard'
import UnitPanel from './UnitPanel'

function PlanPanel({ s, onPlanned, onStale }) {
  const [mode, setMode] = useState(s.planned_mode ?? s.requested_mode)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const locked = !['requested', 'planned'].includes(s.status)
  const needsReason = reasonNeeded(mode, { requestedMode: s.requested_mode, reuse: s.reuse })

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      onPlanned(await api(`/studies/${s.id}/plan`, { method: 'POST', body: { version: s.version, mode, reason: reason.trim() || null } }))
      setReason('')
    } catch (err) {
      if (isStale(err)) { await onStale(); setError('The study changed while you were looking. It has been reloaded — check it, then confirm again.') }
      else setError(err.message)
    } finally { setBusy(false) }
  }

  if (locked) {
    return (
      <Card title="Reuse decision">
        <p className="text-sm"><b>{MODES[s.planned_mode ?? s.requested_mode].label}</b>{s.plan_reason && <span className="opacity-70"> — “{s.plan_reason}”</span>}</p>
        <p className="mt-1 text-xs opacity-70">{s.status === 'in_progress' ? 'Fixed: units are assigned and the survey has started.' : `This study is ${s.status}.`}</p>
      </Card>
    )
  }
  return (
    <Card title={s.status === 'requested' ? 'Your decision (final say)' : 'Re-plan'}>
      <p className="mb-2 text-sm">
        BD Manager asked for <b>{MODES[s.requested_mode].label}</b>
        {s.request_reason ? <span className="opacity-70"> — “{s.request_reason}”</span> : <span className="opacity-60"> (the default)</span>}.
      </p>
      <form onSubmit={submit} className="space-y-2">
        {Object.entries(MODES).map(([k, m]) => {
          const disabled = k === 'reuse_only' && s.reuse.counts.fresh === 0
          return (
            <label key={k} className={`flex cursor-pointer gap-2 rounded border p-2 text-sm ${mode === k ? 'border-brand bg-brand-light' : ''} ${disabled ? 'cursor-not-allowed opacity-40' : ''}`}>
              <input type="radio" name="plan-mode" value={k} checked={mode === k} disabled={disabled} onChange={() => setMode(k)} className="mt-0.5 accent-brand" />
              <span><b>{m.label}</b>{k === s.requested_mode && <span className="ml-1 text-xs opacity-60">(requested)</span>}<br /><span className="text-xs opacity-70">{m.help}</span></span>
            </label>
          )
        })}
        <label htmlFor="plan-reason" className="block text-sm font-medium">
          Reason {needsReason ? <span className="text-red-800">(required — {mode !== s.requested_mode ? 'you are changing what BD asked for' : 'coverage is below the threshold'})</span> : <span className="font-normal opacity-60">(optional)</span>}
        </label>
        <textarea id="plan-reason" rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} className="w-full rounded border px-2 py-1.5 text-sm" />
        <p className="text-xs opacity-70">Coverage is re-checked when you confirm (data may have gone stale since the request). Confirming generates the survey units.</p>
        {error && <p className="rounded bg-red-50 p-2 text-sm text-red-800">{error}</p>}
        <button disabled={busy || (needsReason && reason.trim().length < 3)} className="w-full rounded bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">
          {busy ? 'Planning…' : s.status === 'requested' ? 'Confirm plan and generate units' : 'Re-plan and regenerate units'}
        </button>
      </form>
    </Card>
  )
}

function ClosePanel({ s, onDone }) {
  const [reason, setReason] = useState('')
  const [open, setOpen] = useState(false)
  const [error, setError] = useState(null)
  const running = ['queued', 'running'].includes(s.rollup_job?.status)
  if (running || !['in_progress', 'complete'].includes(s.status)) return null
  const openUnits = s.units.count - s.units.submitted
  const needsReason = s.status === 'complete' || openUnits > 0
  const label = s.status === 'complete' ? 'Re-run the summary (new version)' : openUnits ? `Close study now (${openUnits} unit(s) not submitted)` : 'Roll up now'
  const go = async (e) => {
    e.preventDefault(); setError(null)
    try { await api(`/studies/${s.id}/rollup`, { method: 'POST', body: { version: s.version, reason: reason.trim() || null } }); setOpen(false); setReason(''); onDone() }
    catch (err) { setError(err.message) }
  }
  if (!open) return <button onClick={() => setOpen(true)} className="text-sm text-brand underline">{label}…</button>
  return (
    <Card title={label}>
      <form onSubmit={go} className="space-y-2">
        {openUnits > 0 && s.status !== 'complete' && <p className="text-sm">The summary will use only what has been captured; lanes not surveyed are never filled in, and coverage below 50% gives facts only.</p>}
        {needsReason && <input autoFocus required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (recorded)" className="w-full rounded border px-2 py-1.5 text-sm" />}
        {error && <p className="text-sm text-red-800">{error}</p>}
        <div className="flex gap-2"><button className="rounded bg-brand px-3 py-1.5 text-sm font-semibold text-white">Start roll-up</button>
          <button type="button" onClick={() => setOpen(false)} className="text-sm">Cancel</button></div>
      </form>
    </Card>
  )
}

export default function StudyPage() {
  const { id } = useParams()
  const queryClient = useQueryClient()
  const layers = useMapLayers({ withGrid: false })
  const [flash, setFlash] = useState(null)
  const study = useQuery({ queryKey: ['study', id], queryFn: () => api(`/studies/${id}`),
                          refetchInterval: (q) => (['queued', 'running'].includes(q.state.data?.rollup_job?.status) ? 2000 : false) })
  const s = study.data
  const segments = useQuery({ queryKey: ['study', id, 'segments', s?.version], queryFn: () => api(`/studies/${id}/segments`), enabled: !!s })
  const plan = useQuery({ queryKey: ['study', id, 'units', s?.version], queryFn: () => api(`/studies/${id}/units`),
                          enabled: !!s && s.units.count > 0 })
  const [view, setView] = useState(null)            // 'reuse' | 'units' (default: units once they exist)
  const [selected, setSelected] = useState(new Set())
  const [focus, setFocus] = useState(null)
  const hasUnits = !!plan.data?.units.length
  const mode = view ?? (hasUnits ? 'units' : 'reuse')
  const overlays = useMemo(() => {
    if (!s || !segments.data) return []
    return mode === 'units' && plan.data ? unitOverlays(s, segments.data, plan.data.units, { selected, focus }) : catchmentOverlays(s, segments.data)
  }, [s, segments.data, plan.data, mode, selected, focus])
  const editable = s && ['planned', 'in_progress'].includes(s.status)
  const toggleLane = (feature) => {
    if (!editable || !feature) return
    const id = feature.properties.segment_id
    setSelected((cur) => { const next = new Set(cur); next.has(id) ? next.delete(id) : next.add(id); return next })
  }
  const fit = useMemo(() => (s ? boundsOf(circle(s.lat, s.lon, s.radius_m * 1.05)) : null), [s?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  if (study.isError) return <p className="p-6 text-red-700">{study.error.message}</p>
  if (!s) return <p className="p-6">Loading…</p>
  const p = s.property

  return (
    <div className="mx-auto max-w-6xl p-4">
      <Link to="/" className="text-sm text-brand">← Studies</Link>
      <div className="mt-1 mb-3">
        <p className="text-xs text-brand">Study #{s.id} · <StatusBadge status={s.status} /></p>
        <h1 className="text-xl font-bold">{p.label}</h1>
        <p className="text-xs opacity-70">{[p.locality, p.pincode, p.ward_no && `ward ${p.ward_no}`].filter(Boolean).join(' · ')} · {s.segment_count} lanes, {fmt(s.total_length_m / 1000, 1)} km within {s.radius_m} m</p>
      </div>
      {flash && <div className="mb-3"><Card tone="ok"><p className="text-sm">✓ {flash}</p></Card></div>}

      <div className="grid gap-3 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="min-w-0 space-y-3">
          <RollupStatus study={s} />
          {s.summary && <SummaryCard key={s.summary.id} studyId={s.id} />}
          <ClosePanel s={s} onDone={() => { queryClient.invalidateQueries({ queryKey: ['study', id] }); queryClient.invalidateQueries({ queryKey: ['summary', s.id] }) }} />
          <Card title="Existing survey data">
            <CoverageBar reuse={s.reuse} />
            <p className="mt-2 text-sm">To survey under {MODES[s.planned_mode ?? s.requested_mode].label.toLowerCase()}: <b>{s.survey.segments} lanes · {fmt(s.survey.length_m / 1000, 1)} km</b></p>
          </Card>
          <PlanPanel key={`${s.id}-${s.version}`} s={s} onStale={() => study.refetch()}
                     onPlanned={(next) => {
                       setFlash(`Planned: ${MODES[next.planned_mode].label} — ${next.survey.segments} lanes in ${next.units.count} unit(s).`)
                       queryClient.invalidateQueries({ queryKey: ['study', id] }); queryClient.invalidateQueries({ queryKey: ['studies'] })
                     }} />
          <Card title="Getting there">
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              {[['Address', p.address], ['Landmark', p.landmark], ['Access', p.access_notes]].filter(([, v]) => v)
                .map(([k, v]) => <div key={k} className="contents"><dt className="opacity-60">{k}</dt><dd>{v}</dd></div>)}
            </dl>
            <a className="mt-1 inline-block text-sm text-brand underline" target="_blank" rel="noreferrer"
               href={`https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lon}`}>Directions</a>
          </Card>
        </div>
        <div className="min-w-0 space-y-3">
          {hasUnits && (
            <div className="flex gap-1 text-sm" role="tablist">
              {[['units', 'Units'], ['reuse', 'Reuse']].map(([k, l]) => (
                <button key={k} role="tab" aria-selected={mode === k} onClick={() => setView(k)}
                        className={`rounded-full px-3 py-1 ${mode === k ? 'bg-brand text-white' : 'bg-white ring-1 ring-brand/20'}`}>{l}</button>
              ))}
            </div>
          )}
          <div className="h-[28rem] overflow-hidden rounded-lg">
            <MapView serviceArea={layers.serviceArea} stores={layers.stores} overlays={overlays} fit={fit}
                     onOverlayClick={mode === 'units' ? toggleLane : undefined} />
          </div>
          {mode === 'reuse' ? (
            <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
              {STATE_ORDER.map((k) => <li key={k} className="flex items-center gap-1"><span className="inline-block h-1 w-4 rounded" style={{ background: STATE[k].color }} />{STATE[k].label}</li>)}
              <li className="opacity-70">thick = to survey</li>
            </ul>
          ) : (
            <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
              {plan.data.units.map((u) => <li key={u.id} className="flex items-center gap-1"><span className="inline-block h-1 w-4 rounded" style={{ background: unitColor(plan.data.units, u.id) }} />{u.label}</li>)}
              <li className="opacity-70">thin grey = reused · yellow = selected</li>
            </ul>
          )}
          {plan.data && (
            <UnitPanel plan={plan.data} segments={segments.data} selected={selected} setSelected={setSelected}
                       focus={focus} setFocus={setFocus} onStale={() => study.refetch()}
                       onChanged={(next) => {
                         queryClient.setQueryData(['study', id], next.study)
                         queryClient.setQueryData(['study', id, 'units', next.study.version], next)
                         queryClient.invalidateQueries({ queryKey: ['studies'] })
                       }} />
          )}
        </div>
      </div>
    </div>
  )
}
