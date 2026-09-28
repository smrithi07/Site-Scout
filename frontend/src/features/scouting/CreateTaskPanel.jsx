// BD Manager → BD Executive: turn a report's hotspots into a scout task (docs/DESIGN.md §6).
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'

export default function CreateTaskPanel({ report }) {
  const hotspots = report.result.hotspots
  const users = useQuery({ queryKey: ['demo-users'], queryFn: () => api('/auth/demo-users', { token: '' }) })
  const executives = (users.data ?? []).filter((u) => u.role === 'bd_executive')
  const [picked, setPicked] = useState(() => new Set(hotspots.slice(0, 3).map((h) => h.h3)))
  const [assignee, setAssignee] = useState('')
  const [title, setTitle] = useState(`Scout ${report.label}`.slice(0, 120))
  const [due, setDue] = useState('')
  const [note, setNote] = useState('')
  const [created, setCreated] = useState(null)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      const task = await api('/tasks', { method: 'POST', body: {
        title, note: note || null, due_date: due || null, source_report_id: report.id,
        assignee_id: Number(assignee || executives[0]?.id), hotspot_cells: hotspots.filter((h) => picked.has(h.h3)).map((h) => h.h3),
      } })
      setCreated(task)
    } catch (err) {
      setError(err.message)
    }
  }

  if (created) {
    return (
      <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm">
        Scout task #{created.id} created with {created.hotspot_cells.length} hotspot(s).{' '}
        <Link to={`/tasks/${created.id}`} className="text-brand underline">Open task</Link>
      </p>
    )
  }
  return (
    <form onSubmit={submit} className="space-y-2 rounded-lg border border-brand/15 bg-white p-3 text-sm">
      <div className="font-semibold">Send executives to scout</div>
      <fieldset className="flex flex-wrap gap-2">
        <legend className="sr-only">Hotspots</legend>
        {hotspots.map((h, i) => (
          <label key={h.h3} className={`flex items-center gap-1 rounded-full border px-2 py-0.5 ${picked.has(h.h3) ? 'border-brand bg-brand/10' : 'border-brand/20'}`}>
            <input type="checkbox" checked={picked.has(h.h3)}
                   onChange={() => setPicked((s) => { const n = new Set(s); n.has(h.h3) ? n.delete(h.h3) : n.add(h.h3); return n })} />
            Hotspot {i + 1} · ward {h.ward_no}
          </label>
        ))}
      </fieldset>
      <input value={title} onChange={(e) => setTitle(e.target.value)} className="w-full rounded border px-2 py-1" aria-label="Task title" required minLength={3} />
      <div className="flex flex-wrap gap-2">
        <select value={assignee} onChange={(e) => setAssignee(e.target.value)} className="rounded border px-2 py-1" aria-label="Assign to">
          {executives.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
        </select>
        <label className="flex items-center gap-1">Due <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="rounded border px-2 py-1" /></label>
      </div>
      <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note for the executive (optional)" rows={2} className="w-full rounded border px-2 py-1" />
      {error && <p className="text-red-700">{error}</p>}
      <button disabled={picked.size === 0} className="rounded-md bg-accent px-4 py-1.5 font-semibold text-ink shadow enabled:hover:brightness-95 disabled:opacity-40">
        Create scout task ({picked.size} hotspot{picked.size === 1 ? '' : 's'})
      </button>
    </form>
  )
}
