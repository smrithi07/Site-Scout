// Local locality index search. Ambiguous names return several candidates — the user picks; we never
// guess. Each candidate shows pincode / ward / zone and the boundary it would use.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../api/client'

const KIND = { pincode: 'Pincode', post_office: 'Post office', osm_place: 'Neighbourhood', ward: 'Ward', zone: 'Zone' }

export default function LocalitySearch({ onPick }) {
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250)
    return () => clearTimeout(t)
  }, [q])
  const results = useQuery({
    queryKey: ['localities', debounced],
    queryFn: () => api(`/localities/search?q=${encodeURIComponent(debounced)}`),
    enabled: debounced.length >= 2,
    placeholderData: (prev) => prev,
  })

  return (
    <div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="e.g. Perambur, Velachery, Abhiramapuram"
        className="w-full rounded border px-3 py-2"
        aria-label="Search localities"
      />
      {debounced.length >= 2 && (
        <ul className="mt-2 max-h-72 divide-y overflow-y-auto rounded border bg-white text-sm">
          {results.data?.candidates.map((c) => (
            <li key={c.id}>
              <button
                disabled={!c.in_service_area}
                onClick={() => onPick(c)}
                className="w-full px-3 py-2 text-left hover:bg-brand-light disabled:cursor-not-allowed disabled:opacity-50"
              >
                <div className="flex justify-between gap-2">
                  <span className="font-medium">{c.name}</span>
                  <span className="text-xs whitespace-nowrap text-brand">{KIND[c.kind]}</span>
                </div>
                <div className="text-xs opacity-70">
                  {c.in_service_area
                    ? [c.pincode, c.ward_no && `ward ${c.ward_no}`, c.zone_name && `${c.zone_name} zone`].filter(Boolean).join(' · ')
                    : 'Outside the service area (GCC)'}
                </div>
                {c.in_service_area && (
                  <div className={`text-xs ${c.geometry.approximate ? 'text-amber-700' : 'opacity-60'}`}>
                    Boundary: {c.geometry.label}
                  </div>
                )}
              </button>
            </li>
          ))}
          {results.data?.candidates.length === 0 && (
            <li className="px-3 py-2 opacity-70">No match. Try a pincode, or pick cells on the map.</li>
          )}
        </ul>
      )}
    </div>
  )
}
