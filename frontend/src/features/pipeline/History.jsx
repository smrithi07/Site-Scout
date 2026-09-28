// The property's audit trail, newest first: who did what, from → to, and why (Core rule 3).
import { ROLE_LABELS } from '../../app/auth'
import { STAGE_LABEL } from '../scouting/shared'

const ACTION = {
  created: 'Onboarded', edited: 'Edited', stage_moved: 'Stage moved', follow_up_requested: 'Follow-up requested',
  follow_up_answered: 'Follow-up answered', merged: 'Merged as duplicate', duplicate_dismissed: 'Not a duplicate',
  photo_added: 'Photo added', evaluated: 'Evaluated',
}
const when = (at) => new Date(at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

function detail(e) {
  const d = e.details ?? {}
  if (e.action === 'evaluated') return [e.to_state, d.score != null && `score ${d.score}`, d.hard_flags?.length && `flags: ${d.hard_flags.join(', ')}`].filter(Boolean).join(' · ')
  if (e.action === 'edited' && d.fields) return `changed ${d.fields.join(', ').replaceAll('_', ' ')}`
  return null
}

export default function History({ events }) {
  if (!events) return <p className="text-sm opacity-60">Loading…</p>
  return (
    <ol className="space-y-2.5 border-l-2 border-brand/15 pl-3">
      {[...events].reverse().map((e) => (
        <li key={e.id} className="relative text-sm">
          <span className="absolute top-1.5 -left-[17px] h-2 w-2 rounded-full bg-brand" aria-hidden />
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-semibold">{ACTION[e.action] ?? e.action.replaceAll('_', ' ')}</span>
            {e.from_state && e.to_state && <span>{STAGE_LABEL(e.from_state)} → <b>{STAGE_LABEL(e.to_state)}</b></span>}
            {e.details?.system_transition && <span className="rounded bg-brand/10 px-1 text-xs">automatic</span>}
          </div>
          {e.reason && <p className="opacity-90">“{e.reason}”</p>}
          {detail(e) && <p className="text-xs opacity-70">{detail(e)}</p>}
          <p className="text-xs opacity-60">{e.actor_name ?? ROLE_LABELS[e.actor_role] ?? 'system'} · {when(e.at)}</p>
        </li>
      ))}
    </ol>
  )
}
