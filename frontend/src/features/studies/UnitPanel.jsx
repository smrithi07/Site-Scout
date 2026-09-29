// Survey Manager's unit planner + progress board. Lanes are selected on the map (StudyPage); this
// panel moves / splits / merges them and assigns units. Every edit is re-validated by the API (one
// lane, one unit) and locked on the study version: a 409 reloads the plan and keeps the selection.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import { fmt } from '../../components/ScoreBreakdown'
import { isStale } from '../pipeline/Dialogs'
import { Card } from '../scouting/shared'
import { unitColor } from './reuse'

function Progress({ u }) {
  const pct = u.segment_count ? (100 * (u.surveyed + u.gaps)) / u.segment_count : 0
  return (
    <div className="min-w-24">
      <div className="flex h-1.5 overflow-hidden rounded bg-stone-200">
        <div className="bg-emerald-600" style={{ width: `${(100 * u.surveyed) / u.segment_count}%` }} />
        <div className="bg-amber-500" style={{ width: `${(100 * u.gaps) / u.segment_count}%` }} />
      </div>
      <p className="mt-0.5 text-[11px] opacity-70">{u.surveyed + u.gaps}/{u.segment_count} lanes{u.gaps > 0 && ` · ${u.gaps} could not survey`} · {Math.round(pct)}%</p>
    </div>
  )
}

export default function UnitPanel({ plan, segments, selected, setSelected, focus, setFocus, onChanged, onStale }) {
  const people = useQuery({ queryKey: ['demo-users'], queryFn: () => api('/auth/demo-users'), staleTime: Infinity })
  const execs = (people.data ?? []).filter((u) => u.role === 'survey_executive')
  const [target, setTarget] = useState('')
  const [mergeWith, setMergeWith] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const { study, units } = plan
  const editable = ['planned', 'in_progress'].includes(study.status)
  const label = Object.fromEntries(units.map((u) => [u.id, u.label]))

  const unitOf = Object.fromEntries((segments?.features ?? []).map((f) => [f.properties.segment_id, f.properties.unit_id]))
  const fromUnits = [...new Set([...selected].map((id) => unitOf[id]))]
  const canSplit = fromUnits.length === 1 && selected.size < (units.find((u) => u.id === fromUnits[0])?.segment_count ?? 0)

  const run = async (path, body, ok, after) => {
    setBusy(true); setMsg(null)
    try {
      const next = await api(`/studies/${study.id}/units${path}`, { method: 'POST', body: { version: study.version, ...body } })
      onChanged(next); after?.(); setMsg({ tone: 'ok', text: ok })
    } catch (err) {
      if (isStale(err)) { await onStale(); setMsg({ tone: 'warn', text: 'Someone else changed this plan. It has been reloaded — check, then try again.' }) }
      else setMsg({ tone: 'warn', text: err.message })
    } finally { setBusy(false) }
  }
  const s = study.units

  return (
    <Card title={study.status === 'in_progress' ? 'Units and progress' : 'Survey units'}>
      {s.count > 0 && (
        <p className="mb-2 text-sm">
          {s.count} units · {fmt(s.total_minutes / 60, 1)} h in total ({fmt(s.minutes_min / 60, 1)}–{fmt(s.minutes_max / 60, 1)} h each) · {s.assigned} assigned
          {study.status === 'in_progress' && <> · <b>{s.handled}/{s.lanes} lanes done ({s.progress_pct}%)</b></>}
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b text-left text-xs uppercase opacity-60">
            <th className="py-1 pr-2 font-medium">Unit</th><th className="pr-2 font-medium">Lanes</th><th className="pr-2 font-medium">Est.</th>
            <th className="pr-2 font-medium">Pieces</th><th className="pr-2 font-medium">Progress</th><th className="font-medium">Surveyor</th>
          </tr></thead>
          <tbody>
            {units.map((u) => (
              <tr key={u.id} onClick={() => setFocus(focus === u.id ? null : u.id)}
                  className={`cursor-pointer border-b last:border-0 ${focus === u.id ? 'bg-brand-light' : 'hover:bg-stone-50'}`}>
                <td className="py-1.5 pr-2 font-semibold whitespace-nowrap">
                  <span className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: unitColor(units, u.id) }} />{u.label}
                </td>
                <td className="pr-2 tabular-nums">{u.segment_count} <span className="text-xs opacity-60">· {fmt(u.length_m / 1000, 2)} km</span></td>
                <td className="pr-2 tabular-nums whitespace-nowrap">{fmt(u.minutes / 60, 1)} h</td>
                <td className="pr-2 tabular-nums" title="disconnected parts of the unit's walk">{u.pieces}</td>
                <td className="pr-2"><Progress u={u} /></td>
                <td onClick={(e) => e.stopPropagation()}>
                  <select aria-label={`Surveyor for ${u.label}`} value={u.assignee_id ?? ''} disabled={!editable || busy || u.status === 'submitted'}
                          onChange={(e) => run(`/${u.id}/assign`, { assignee_id: e.target.value ? Number(e.target.value) : null },
                                               e.target.value ? `${u.label} assigned.` : `${u.label} unassigned.`)}
                          className="max-w-40 rounded border px-1 py-0.5 text-xs">
                    <option value="">— unassigned —</option>
                    {execs.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editable && (
        <div className="mt-3 space-y-2 border-t pt-2 text-sm">
          {selected.size === 0
            ? <p className="text-xs opacity-70">Tap lanes on the map to select them, then move them or split them into a new unit. Tap a unit row to highlight it.</p>
            : (
              <div className="space-y-2 rounded-md bg-accent/30 p-2">
                <p><b>{selected.size} lane{selected.size > 1 && 's'} selected</b> from {fromUnits.map((id) => label[id]).join(', ')}
                  <button onClick={() => setSelected(new Set())} className="ml-2 text-xs underline">clear</button></p>
                <div className="flex flex-wrap items-center gap-2">
                  <select value={target} onChange={(e) => setTarget(e.target.value)} className="rounded border px-1 py-1 text-sm" aria-label="Move to unit">
                    <option value="">Move to…</option>
                    {units.map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
                  </select>
                  <button disabled={!target || busy} onClick={() => run('/move', { segment_ids: [...selected], to_unit_id: Number(target) },
                                                                        `Moved ${selected.size} lane(s) to ${label[target]}.`, () => { setSelected(new Set()); setTarget('') })}
                          className="rounded bg-brand px-3 py-1 font-semibold text-white disabled:opacity-40">Move</button>
                  <button disabled={!canSplit || busy} title={canSplit ? '' : 'Select some (not all) lanes of one unit'}
                          onClick={() => run(`/${fromUnits[0]}/split`, { segment_ids: [...selected] }, `Split ${selected.size} lane(s) into a new unit.`, () => setSelected(new Set()))}
                          className="rounded border border-brand px-3 py-1 text-brand disabled:opacity-40">Split into new unit</button>
                </div>
              </div>
            )}
          {focus != null && label[focus] && (
            <div className="flex flex-wrap items-center gap-2">
              <span>Merge <b>{label[focus]}</b> with</span>
              <select value={mergeWith} onChange={(e) => setMergeWith(e.target.value)} className="rounded border px-1 py-1 text-sm" aria-label="Merge with unit">
                <option value="">…</option>
                {units.filter((u) => u.id !== focus).map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
              </select>
              <button disabled={!mergeWith || busy} onClick={() => run('/merge', { unit_ids: [focus, Number(mergeWith)] },
                                                                      `Merged ${label[mergeWith]} into ${label[focus]}.`, () => setMergeWith(''))}
                      className="rounded border border-brand px-3 py-1 text-brand disabled:opacity-40">Merge</button>
            </div>
          )}
        </div>
      )}
      {msg && <p className={`mt-2 rounded p-2 text-sm ${msg.tone === 'ok' ? 'bg-emerald-50 text-emerald-900' : 'bg-amber-50 text-amber-900'}`}>{msg.text}</p>}
    </Card>
  )
}
