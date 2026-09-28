// BD Manager: request a catchment study. Shows what the request would find (coverage, stale,
// oldest reused age) before anything is written, then the reuse mode — an override needs a reason.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import { fmt } from '../../components/ScoreBreakdown'
import { Modal, isStale } from '../pipeline/Dialogs'
import { CoverageBar, DEFAULT_MODE, MODES, reasonNeeded } from './reuse'

export default function RequestStudyDialog({ property: p, onClose, onDone, onStale }) {
  const preview = useQuery({ queryKey: ['study-preview', p.id], queryFn: () => api(`/studies/preview?property_id=${p.id}`) })
  const [mode, setMode] = useState(DEFAULT_MODE)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const pv = preview.data
  const needsReason = pv && reasonNeeded(mode, { reuse: pv.reuse })

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      onDone(await api('/studies', { method: 'POST', body: { property_id: p.id, version: p.version, mode, reason: reason.trim() || null } }))
    } catch (err) {
      if (isStale(err)) { await onStale(); setError('This property changed while you were looking. It has been reloaded — check it, then request again.') }
      else setError(err.message)
    } finally { setBusy(false) }
  }

  return (
    <Modal title="Request a catchment study" onClose={onClose}>
      <p className="text-sm opacity-70">#{p.id} {p.label}</p>
      {preview.isLoading && <p className="mt-3 animate-pulse text-sm">Checking existing survey data…</p>}
      {preview.isError && <p className="mt-3 text-sm text-red-800">{preview.error.message}</p>}
      {pv && (
        <form onSubmit={submit} className="mt-3 space-y-3">
          <div className="rounded-md bg-brand-light p-2.5">
            <p className="mb-1.5 text-xs opacity-70">{pv.segment_count} lanes · {fmt(pv.total_length_m / 1000, 1)} km of road within {pv.radius_m} m</p>
            <CoverageBar reuse={pv.reuse} />
          </div>
          <fieldset className="space-y-1">
            <legend className="mb-1 text-sm font-medium">What should the survey team do?</legend>
            {Object.entries(MODES).map(([k, m]) => {
              const disabled = k === 'reuse_only' && pv.reuse.counts.fresh === 0
              return (
                <label key={k} className={`flex cursor-pointer gap-2 rounded border p-2 text-sm ${mode === k ? 'border-brand bg-brand-light' : ''} ${disabled ? 'cursor-not-allowed opacity-40' : ''}`}>
                  <input type="radio" name="mode" value={k} checked={mode === k} disabled={disabled} onChange={() => setMode(k)} className="mt-0.5 accent-brand" />
                  <span><b>{m.label}</b>{k === DEFAULT_MODE && <span className="ml-1 text-xs opacity-60">(default)</span>}<br /><span className="text-xs opacity-70">{m.help}</span></span>
                </label>
              )
            })}
          </fieldset>
          <div>
            <label htmlFor="study-reason" className="text-sm font-medium">
              Reason {needsReason ? <span className="text-red-800">(required — this overrides the default{mode === 'reuse_only' && !pv.reuse.meets_threshold ? ', coverage is below the threshold' : ''})</span> : <span className="font-normal opacity-60">(optional)</span>}
            </label>
            <textarea id="study-reason" rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)}
                      className="mt-1 w-full rounded border px-2 py-1.5 text-sm" />
          </div>
          <p className="text-xs opacity-70">The Survey Manager makes the final reuse decision when planning.</p>
          {error && <p className="rounded bg-red-50 p-2 text-sm text-red-800">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="rounded px-3 py-2 text-sm">Cancel</button>
            <button disabled={busy || (needsReason && reason.trim().length < 3)} className="rounded bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">
              {busy ? 'Requesting…' : 'Request study'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}
