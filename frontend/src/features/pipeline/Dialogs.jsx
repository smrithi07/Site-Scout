// The manager's two pipeline actions. Both send the version the manager was looking at; if someone
// else changed the property meanwhile the API answers 409, the page re-reads it, and the dialog stays
// open (reason kept) so the manager decides again on current data instead of overwriting blind.
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { STAGE_LABEL } from '../scouting/shared'

export const isStale = (e) => e?.status === 409 && /changed by someone else|changed since you loaded/i.test(e.message)

const PRESETS = {
  under_review: ['Worth a closer look'],
  shortlisted: ['Strong fit and rent within band', 'Good frontage and visibility'],
  rejected: ['Rent too high for the area', 'Too close to an existing Savomart', 'Poor visibility or access', 'Owner not willing'],
  on_hold: ['Waiting on the owner', 'Revisit next quarter'],
  approved: ['Study supports opening here'],
}
const FOLLOW_UP_KINDS = [['photos', 'More photos'], ['revisit', 'Revisit the site'], ['rent_check', 'Check the rent'], ['other', 'Something else']]

function Modal({ title, onClose, children }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/40 md:items-center" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}
           className="w-full max-w-md rounded-t-xl bg-white p-4 shadow-xl md:rounded-xl">
        <h2 className="text-lg font-bold">{title}</h2>
        {children}
      </div>
    </div>
  )
}

function useSubmit(onStale) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const run = async (fn) => {
    setBusy(true); setError(null)
    try { return await fn() } catch (e) {
      if (isStale(e)) { await onStale(); setError({ stale: true, text: 'Someone else changed this property while you were looking. It has been reloaded — check it, then confirm again.' }) }
      else setError({ text: e.message })
    } finally { setBusy(false) }
  }
  return { busy, error, run }
}

export function StageDialog({ property: p, to, onClose, onDone, onStale }) {
  const [reason, setReason] = useState('')
  const { busy, error, run } = useSubmit(onStale)
  const stillAllowed = p.pipeline.moves.includes(to)
  const submit = (e) => {
    e.preventDefault()
    run(async () => onDone(await api(`/properties/${p.id}/stage`, { method: 'POST', body: { to, reason, version: p.version } }), reason))
  }
  return (
    <Modal title={`Move to ${STAGE_LABEL(to)}`} onClose={onClose}>
      <p className="text-sm opacity-70">#{p.id} {p.label} · now {STAGE_LABEL(p.stage)}</p>
      <form onSubmit={submit} className="mt-3 space-y-2">
        <label className="block text-sm font-medium" htmlFor="reason">Why? <span className="font-normal opacity-60">(recorded in the history)</span></label>
        <div className="flex flex-wrap gap-1">
          {(PRESETS[to] ?? []).map((r) => (
            <button type="button" key={r} onClick={() => setReason(r)} className="rounded-full border border-brand/30 px-2 py-0.5 text-xs hover:bg-brand-light">{r}</button>
          ))}
        </div>
        <textarea id="reason" required minLength={3} maxLength={500} rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
                  className="w-full rounded border px-2 py-1.5 text-sm" autoFocus />
        {error && <p className={`rounded p-2 text-sm ${error.stale ? 'bg-amber-50 text-amber-900' : 'bg-red-50 text-red-800'}`}>{error.text}</p>}
        {!stillAllowed && <p className="text-sm text-red-800">It is now {STAGE_LABEL(p.stage)}; moving to {STAGE_LABEL(to)} is no longer possible from here.</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="rounded px-3 py-2 text-sm">Cancel</button>
          <button disabled={busy || !stillAllowed || reason.trim().length < 3}
                  className="rounded bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">
            {busy ? 'Moving…' : `Move to ${STAGE_LABEL(to)}`}
          </button>
        </div>
      </form>
    </Modal>
  )
}

export function FollowUpDialog({ property: p, onClose, onDone, onStale }) {
  const [kind, setKind] = useState('photos')
  const [message, setMessage] = useState('')
  const { busy, error, run } = useSubmit(onStale)
  const allowed = p.pipeline.follow_up.allowed
  const submit = (e) => {
    e.preventDefault()
    run(async () => onDone(await api(`/properties/${p.id}/follow-ups`, { method: 'POST', body: { kind, message, version: p.version } })))
  }
  return (
    <Modal title="Ask the executive" onClose={onClose}>
      <p className="text-sm opacity-70">Goes to {p.pipeline.follow_up.assignee ?? 'the executive'}; the property waits in “needs follow up” until they answer.</p>
      <form onSubmit={submit} className="mt-3 space-y-2">
        <div className="grid grid-cols-2 gap-1">
          {FOLLOW_UP_KINDS.map(([k, label]) => (
            <label key={k} className={`cursor-pointer rounded border px-2 py-1.5 text-sm ${kind === k ? 'border-brand bg-brand-light font-semibold' : ''}`}>
              <input type="radio" name="kind" value={k} checked={kind === k} onChange={() => setKind(k)} className="sr-only" />{label}
            </label>
          ))}
        </div>
        <textarea required minLength={3} maxLength={1000} rows={3} value={message} onChange={(e) => setMessage(e.target.value)}
                  placeholder="What exactly do you need?" className="w-full rounded border px-2 py-1.5 text-sm" autoFocus />
        {error && <p className={`rounded p-2 text-sm ${error.stale ? 'bg-amber-50 text-amber-900' : 'bg-red-50 text-red-800'}`}>{error.text}</p>}
        {!allowed && <p className="text-sm text-red-800">Not possible now: {p.pipeline.follow_up.why}.</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="rounded px-3 py-2 text-sm">Cancel</button>
          <button disabled={busy || !allowed || message.trim().length < 3}
                  className="rounded bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{busy ? 'Sending…' : 'Send request'}</button>
        </div>
      </form>
    </Modal>
  )
}
