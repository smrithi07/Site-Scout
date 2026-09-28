// A scouted property after saving: what happened (warnings, duplicate question, evaluation), and
// what's left to add (photos, notes, follow-up answers). The BD Manager gets the review page instead.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, apiUpload } from '../../api/client'
import { useAuth } from '../../app/auth'
import MapView from '../../components/MapView'
import { fmt } from '../../components/ScoreBreakdown'
import { useMapLayers } from '../areas/AnalysePage'
import ReviewPage from '../pipeline/ReviewPage'
import { pinOverlay } from './mapLayers'
import { Card, OUTCOME_STYLE, Photo, STAGE_LABEL } from './shared'

export default function PropertyPage() {
  const { user } = useAuth()
  return user.role === 'bd_manager' ? <ReviewPage /> : <ExecPropertyPage />
}

function ExecPropertyPage() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const layers = useMapLayers({ withGrid: false })
  const [note, setNote] = useState('')
  const [answer, setAnswer] = useState({})
  const [msg, setMsg] = useState(null)
  const [uploading, setUploading] = useState(false)

  const prop = useQuery({
    queryKey: ['property', id],
    queryFn: () => api(`/properties/${id}`),
    refetchInterval: (q) => (q.state.data?.evaluation_status === 'pending' && q.state.data?.evaluation_job?.status !== 'failed' ? 2000 : false),
  })
  const p = prop.data
  const overlays = useMemo(() => (p ? pinOverlay(p.lat, p.lon, p.gps_accuracy_m) : []), [p?.lat, p?.lon]) // eslint-disable-line react-hooks/exhaustive-deps
  const fit = useMemo(() => (p ? [[p.lon - 0.003, p.lat - 0.003], [p.lon + 0.003, p.lat + 0.003]] : null), [p?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['property', id] })
  const act = async (fn, ok) => {
    setMsg(null)
    try { await fn(); setMsg({ tone: 'ok', text: ok }); refresh() } catch (e) { setMsg({ tone: 'warn', text: e.message }) }
  }

  if (prop.isError) return <p className="p-6 text-red-700">{prop.error.message}</p>
  if (!p) return <p className="p-6">Loading…</p>
  const r = p.review ?? {}
  const openFollowUps = (p.follow_ups ?? []).filter((f) => f.status === 'open' && f.assignee_id === user.id)

  if (p.status === 'merged') {
    // Kept for the record, but all work happens on the original.
    return (
      <div className="mx-auto max-w-xl space-y-3 p-4">
        {msg && <Card tone={msg.tone}><p className="text-sm">{msg.text}</p></Card>}
        <p className="text-xs text-brand">#{p.id} · merged</p>
        <h1 className="text-xl font-bold">{p.label}</h1>
        <Card tone="warn">
          This entry is the same property as <Link to={`/properties/${p.duplicate_of}`} className="font-semibold underline">#{p.duplicate_of}</Link>.
          Its location notes were added there; continue on that property.
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-xl space-y-3 p-4">
      {params.get('new') && <Card tone="ok">✓ Saved. {p.missing_fields.includes('photos') && 'Add photos below when you can.'}</Card>}
      <div>
        <p className="text-xs text-brand">#{p.id} · {STAGE_LABEL(p.stage)}{p.status !== 'active' && ` · ${STAGE_LABEL(p.status)}`}</p>
        <h1 className="text-xl font-bold">{p.label}</h1>
        <p className="text-xs opacity-70">{[p.locality, p.pincode, p.ward_no && `ward ${p.ward_no}`].filter(Boolean).join(' · ')}</p>
      </div>
      <div className="h-44 overflow-hidden rounded-lg"><MapView serviceArea={layers.serviceArea} stores={layers.stores} overlays={overlays} fit={fit} /></div>

      {/* Evaluation */}
      <Card title="Evaluation">
        {p.evaluation_status === 'pending' && p.evaluation_job?.status !== 'failed' && <p className="animate-pulse text-sm">Evaluating…</p>}
        {p.evaluation_job?.status === 'failed' && (
          <p className="text-sm text-red-700">Evaluation failed at {p.evaluation_job.error?.split(':')[0]} — the property is saved. <Link to={`/jobs/${p.evaluation_job.id}`} className="underline">Retry</Link></p>
        )}
        {r.outcome && (
          <div className="text-sm">
            <span className={`rounded-full px-2 py-0.5 font-semibold ${OUTCOME_STYLE[r.outcome]}`}>{r.outcome}</span>
            {r.score != null && <span className="ml-2 tabular-nums">{fmt(r.score)}/100{r.provisional && ' (provisional)'}</span>}
            {r.confidence && <span className="ml-2 opacity-70">{r.confidence} confidence</span>}
            {r.stale && <span className="ml-2 text-amber-700">updating after your edit…</span>}
            {r.outcome_reasons?.length > 0 && <p className="mt-1 opacity-80">{r.outcome_reasons.join('; ')}</p>}
            {r.top_risks?.length > 0 && (
              <ul className="mt-2 space-y-0.5">
                {r.top_risks.map((x) => <li key={x.rule_id}><span className="text-xs uppercase opacity-60">{x.severity}</span> {x.message}</li>)}
              </ul>
            )}
          </div>
        )}
      </Card>

      {/* Duplicate question — an explicit choice, never a silent merge */}
      {p.status === 'possible_duplicate' && (
        <Card title="Possible duplicate" tone="warn">
          <p className="text-sm">Existing properties within 25 m with a similar name:</p>
          <ul className="mt-2 space-y-2">
            {p.duplicate_candidates.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-2 text-sm">
                <span>#{c.id} “{c.label}” · {fmt(c.distance_m, 0)} m</span>
                <button onClick={() => act(() => api(`/properties/${p.id}/duplicate-resolution`, { method: 'POST', body: { choice: 'same', target_id: c.id } }),
                                           'Marked as the same property — your notes were added to it.')}
                        className="rounded border border-brand px-2 py-1 text-brand">Same property</button>
              </li>
            ))}
          </ul>
          <button onClick={() => act(() => api(`/properties/${p.id}/duplicate-resolution`, { method: 'POST', body: { choice: 'different' } }),
                                     'Kept as a separate property.')}
                  className="mt-3 w-full rounded-md bg-white px-3 py-2 text-sm font-semibold ring-1 ring-brand/30">Different property</button>
        </Card>
      )}

      {/* Follow-ups for me */}
      {openFollowUps.map((f) => (
        <Card key={f.id} title={`Manager asks: ${f.kind.replace('_', ' ')}`} tone="warn">
          <p className="text-sm">{f.message}</p>
          <form onSubmit={(e) => { e.preventDefault(); act(() => api(`/follow-ups/${f.id}/respond`, { method: 'POST', body: { response: answer[f.id] } }), 'Answered — back with the manager for review.') }}
                className="mt-2 flex gap-2">
            <input required minLength={3} value={answer[f.id] ?? ''} onChange={(e) => setAnswer((a) => ({ ...a, [f.id]: e.target.value }))}
                   placeholder="Your answer" className="min-w-0 flex-1 rounded border px-2 py-1.5 text-sm" />
            <button className="rounded bg-accent px-3 font-semibold text-ink">Send</button>
          </form>
        </Card>
      ))}

      {msg && <Card tone={msg.tone}><p className="text-sm">{msg.text}</p></Card>}

      {p.warnings.filter((w) => w.code !== 'possible_duplicate').length > 0 && (
        <Card title="Check these" tone="warn">
          <ul className="list-disc space-y-0.5 pl-5 text-sm">{p.warnings.filter((w) => w.code !== 'possible_duplicate').map((w) => <li key={w.code}>{w.message}</li>)}</ul>
        </Card>
      )}
      {p.missing_fields.filter((f) => f !== 'photos').length > 0 && (
        <Card tone="warn"><p className="text-sm">Missing: {p.missing_fields.filter((f) => f !== 'photos').join(', ').replaceAll('_', ' ')} — the outcome stays “Needs Info” until added.</p></Card>
      )}

      {/* Photos — separate from the save, so a failed upload never loses the property */}
      <Card title={`Photos (${p.photos?.length ?? 0})`}>
        <div className="flex flex-wrap gap-2">{p.photos?.map((ph) => <Photo key={ph.id} propertyId={p.id} photo={ph} />)}</div>
        <label className="mt-2 inline-block cursor-pointer rounded-md bg-brand px-3 py-2 text-sm font-semibold text-white">
          {uploading ? 'Uploading…' : '＋ Add photo'}
          <input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" className="sr-only"
                 onChange={async (e) => {
                   const file = e.target.files?.[0]
                   e.target.value = ''
                   if (!file) return
                   setUploading(true)
                   await act(() => apiUpload(`/properties/${p.id}/photos`, file), 'Photo added.')
                   setUploading(false)
                 }} />
        </label>
        {p.missing_fields.includes('photos') && <p className="mt-1 text-xs opacity-70">No photos yet — the property is flagged incomplete until one is added.</p>}
      </Card>

      {/* Notes */}
      <Card title="Notes">
        <ul className="space-y-1 text-sm">{p.notes?.map((n) => <li key={n.id}><span className="text-xs uppercase opacity-50">{n.kind.replace('_', ' ')}</span> {n.text}</li>)}</ul>
        <form onSubmit={(e) => { e.preventDefault(); act(() => api(`/properties/${p.id}/notes`, { method: 'POST', body: { text: note } }).then(() => setNote('')), 'Note added.') }}
              className="mt-2 flex gap-2">
          <input value={note} onChange={(e) => setNote(e.target.value)} required placeholder="Add a note" className="min-w-0 flex-1 rounded border px-2 py-1.5 text-sm" />
          <button className="rounded border border-brand px-3 text-sm text-brand">Add</button>
        </form>
      </Card>

      <Card title="Details">
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
          {[['Rent', p.monthly_rent != null && `₹${fmt(p.monthly_rent, 0)} ${p.rent_unit?.replaceAll('_', ' ')}`], ['Area', p.area_sqft && `${fmt(p.area_sqft, 0)} sq ft`],
            ['Deposit', p.security_deposit != null && `₹${fmt(p.security_deposit, 0)}`], ['Frontage', p.frontage_ft && `${p.frontage_ft} ft`],
            ['Road width', p.road_width_ft && `${p.road_width_ft} ft`], ['Floor', p.floor], ['Visibility', p.visibility], ['Access', p.accessibility],
            ['Parking', p.parking], ['Condition', p.condition], ['Owner', p.owner_name], ['Phone', p.owner_phone],
            ['Address', p.address], ['Landmark', p.landmark], ['GPS', p.gps_accuracy_m != null && `±${fmt(p.gps_accuracy_m, 0)} m`]]
            .filter(([, v]) => v).map(([k, v]) => <div key={k} className="contents"><dt className="opacity-60">{k}</dt><dd>{v}</dd></div>)}
        </dl>
      </Card>
    </div>
  )
}
