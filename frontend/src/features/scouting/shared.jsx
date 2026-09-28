// Pieces shared by the executive's property page, the manager's review page and the board.
import { useEffect, useState } from 'react'
import { apiBlob } from '../../api/client'

export const OUTCOME_STYLE = {
  'Strong Fit': 'bg-emerald-100 text-emerald-900', Consider: 'bg-sky-100 text-sky-900',
  'Weak Fit': 'bg-stone-200 text-stone-800', 'Needs Info': 'bg-amber-100 text-amber-900',
}
export const OUTCOME_RANK = { 'Strong Fit': 0, Consider: 1, 'Needs Info': 2, 'Weak Fit': 3 }
export const STAGE_LABEL = (s) => s.replaceAll('_', ' ')

export function OutcomeBadge({ outcome, className = '' }) {
  if (!outcome) return null
  return <span className={`rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${OUTCOME_STYLE[outcome]} ${className}`}>{outcome}</span>
}

export function Photo({ propertyId, photo, size = 'h-24 w-24' }) {
  const [url, setUrl] = useState(null)
  useEffect(() => {
    let alive = true, obj
    apiBlob(`/properties/${propertyId}/photos/${photo.id}`).then((b) => { obj = URL.createObjectURL(b); if (alive) setUrl(obj) }).catch(() => {})
    return () => { alive = false; if (obj) URL.revokeObjectURL(obj) }
  }, [propertyId, photo.id])
  return url
    ? <a href={url} target="_blank" rel="noreferrer"><img src={url} alt={photo.filename} className={`${size} rounded-md object-cover`} /></a>
    : <div className={`${size} animate-pulse rounded-md bg-brand/10`} />
}

export function Card({ title, children, tone = 'default', action }) {
  const tones = { default: 'border-brand/15 bg-white', warn: 'border-amber-200 bg-amber-50', ok: 'border-emerald-200 bg-emerald-50',
                  bad: 'border-red-200 bg-red-50' }
  return (
    <section className={`rounded-lg border p-3 ${tones[tone]}`}>
      {(title || action) && (
        <div className="mb-1.5 flex items-center gap-2">
          {title && <h2 className="text-sm font-semibold">{title}</h2>}
          {action && <div className="ml-auto">{action}</div>}
        </div>
      )}
      {children}
    </section>
  )
}
