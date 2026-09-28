// Core rule 1 made visible: every value says whether it was observed, a proxy, mock, or missing.
const STYLES = {
  observed: { label: 'observed', className: 'bg-emerald-50 text-emerald-800 border-emerald-200' },
  observed_lower_bound: { label: 'observed · lower bound', className: 'bg-amber-50 text-amber-800 border-amber-200' },
  proxy: { label: 'proxy', className: 'bg-sky-50 text-sky-800 border-sky-200' },
  mock: { label: 'mock', className: 'bg-stone-100 text-stone-700 border-stone-300' },
  missing: { label: 'missing', className: 'bg-white text-red-700 border-red-300 border-dashed' },
}

export default function ProvenanceBadge({ value }) {
  const s = STYLES[value] ?? { label: value, className: 'bg-stone-100 text-stone-700 border-stone-300' }
  return <span className={`inline-block rounded border px-1.5 py-0.5 text-xs whitespace-nowrap ${s.className}`}>{s.label}</span>
}
