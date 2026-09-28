// Live job progress (docs/DESIGN.md §9): every step with its status, the failed step named with its
// error, and a retry that resumes from that step (reason required — it goes to the audit log).
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api/client'

const STEP_LABELS = {
  resolve: 'Resolve area', gather: 'Gather facts', score: 'Score', hotspots: 'Find hotspots',
  narrative: 'Write narrative', validate: 'Check narrative', save: 'Save report',
}
const ICON = { pending: '○', running: '◐', done: '●', failed: '✕' }
const TERMINAL = new Set(['succeeded', 'failed'])

export default function JobProgress({ jobId, onSucceeded }) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const [retryError, setRetryError] = useState(null)
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api(`/jobs/${jobId}`),
    refetchInterval: (q) => (TERMINAL.has(q.state.data?.status) ? false : 1000),
  })

  const data = job.data
  useEffect(() => {
    if (data?.status === 'succeeded') onSucceeded?.(data.steps.at(-1)?.output ?? {})
  }, [data?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  const retry = async (e) => {
    e.preventDefault()
    setRetryError(null)
    try {
      await api(`/jobs/${jobId}/retry`, { method: 'POST', body: { reason, version: data.version } })
      setReason('')
      queryClient.invalidateQueries({ queryKey: ['job', jobId] })
    } catch (err) {
      setRetryError(err.status === 409 ? 'Someone else already retried this job — refreshing.' : err.message)
      queryClient.invalidateQueries({ queryKey: ['job', jobId] })
    }
  }

  if (job.isError) return <p className="text-sm text-red-700">Can't load job {jobId}: {job.error.message}</p>
  if (!data) return <p className="text-sm">Starting…</p>

  return (
    <div className="rounded-lg border border-brand/20 bg-white p-3" aria-live="polite">
      <div className="mb-2 flex items-center justify-between text-sm">
        <span className="font-semibold">Analysis #{jobId}</span>
        <span className={data.status === 'failed' ? 'font-semibold text-red-700' : 'text-brand'}>{data.status}</span>
      </div>
      <ol className="space-y-1 text-sm">
        {data.steps.map((s) => (
          <li key={s.idx} className={`flex items-center gap-2 ${s.status === 'failed' ? 'text-red-700' : ''}`}>
            <span className={`w-4 text-center ${s.status === 'running' ? 'animate-pulse text-brand' : ''}`}>{ICON[s.status]}</span>
            <span className={s.status === 'pending' ? 'opacity-50' : ''}>{STEP_LABELS[s.name] ?? s.name}</span>
            {s.attempts > 1 && <span className="text-xs opacity-60">attempt {s.attempts}</span>}
          </li>
        ))}
      </ol>
      {data.status === 'failed' && (
        <form onSubmit={retry} className="mt-3 border-t pt-3 text-sm">
          <p className="text-red-700">
            Failed at <strong>{STEP_LABELS[data.error?.split(':')[0]] ?? data.current_step}</strong>: {data.error?.split(': ').slice(1).join(': ')}
          </p>
          <p className="mt-1 opacity-70">Finished steps are kept; a retry resumes from the failed step.</p>
          <div className="mt-2 flex gap-2">
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason for retrying (audited)"
              className="min-w-0 flex-1 rounded border px-2 py-1"
              minLength={3}
              required
            />
            <button className="rounded bg-accent px-3 py-1 font-semibold text-ink hover:brightness-95">Retry</button>
          </div>
          {retryError && <p className="mt-1 text-red-700">{retryError}</p>}
        </form>
      )}
    </div>
  )
}
