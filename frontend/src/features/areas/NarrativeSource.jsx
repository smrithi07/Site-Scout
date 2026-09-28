// Who wrote the narrative, and whether anything degraded on the way (docs/DESIGN.md §9: a
// "degraded" banner listing every fallback actually used).
const NAMES = { gemini: 'Gemini', groq: 'Groq', template: 'template' }

function describe(attempts = []) {
  const problems = attempts.filter((a) => ['error', 'invalid'].includes(a.status))
  const parts = problems.map((a) => {
    const code = a.error?.match(/HTTP (\d{3})/)?.[1]
    return `${NAMES[a.provider] ?? a.provider}: ${a.status === 'invalid' ? 'rejected by fact-checker' : code ? `HTTP ${code}` : 'error'}`
  })
  const skipped = attempts.filter((a) => a.status === 'skipped').map((a) => a.reason)
  return { problems: parts, skipped }
}

export default function NarrativeSource({ source, meta = {} }) {
  const { problems, skipped } = describe(meta.attempts)
  const byAI = source !== 'template'
  return (
    <div className="text-xs">
      <span className={`rounded-full px-2 py-0.5 ${byAI ? 'bg-brand/10 text-brand' : 'bg-stone-100 text-stone-700'}`}>
        {byAI ? `Written by ${NAMES[source]} (${meta.model}) from the fact sheet` : 'Written by the deterministic template'}
      </span>
      {byAI && meta.cached && <span className="ml-2 opacity-70">reused from an identical earlier analysis — no new AI call</span>}
      {byAI && problems.length > 0 && <span className="ml-2 opacity-70">after {problems.join(', ')}</span>}
      {!byAI && (problems.length > 0 || skipped.length > 0) && (
        <p className="mt-2 rounded border border-amber-200 bg-amber-50 p-2 text-amber-900">
          <strong>Degraded:</strong> the AI narrative was unavailable
          {problems.length > 0 && <> ({problems.join('; ')})</>}
          {skipped.length > 0 && <> — {skipped.join('; ')}</>}. The text below comes from the template, built from the same verified facts.
        </p>
      )}
    </div>
  )
}
