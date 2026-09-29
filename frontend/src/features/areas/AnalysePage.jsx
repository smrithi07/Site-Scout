// M1 area selection → preview → run. Three ways in (pincode, locality, cells on the map), all
// resolved by the API to the same cell set; after that the user can click cells to add/remove.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { useAuth } from '../../app/auth'
import JobProgress from '../../components/JobProgress'
import MapView, { boundsOf } from '../../components/MapView'
import LocalitySearch from './LocalitySearch'

const MODES = [
  { id: 'pincode', label: 'Pincode' },
  { id: 'locality', label: 'Locality' },
  { id: 'cells', label: 'Pick cells' },
]

function toggle(set, id) {
  const next = new Set(set)
  next.has(id) ? next.delete(id) : next.add(id)
  return next
}

export function useMapLayers({ withGrid = true } = {}) {
  // The selection grid is BD-Manager-only; other screens ask for outline + stores alone. Stores are
  // BD-only on the API, so survey roles don't ask (they'd only get a 403).
  const { user } = useAuth()
  const bd = ['bd_manager', 'bd_executive'].includes(user?.role)
  const grid = useQuery({ queryKey: ['grid'], queryFn: () => api('/areas/grid'), staleTime: Infinity, enabled: withGrid })
  const serviceArea = useQuery({ queryKey: ['service-area'], queryFn: () => api('/reference/service-area'), staleTime: Infinity })
  const stores = useQuery({ queryKey: ['stores'], queryFn: () => api('/reference/stores'), staleTime: Infinity, enabled: bd })
  return { grid: grid.data, serviceArea: serviceArea.data, stores: stores.data, error: grid.error ?? serviceArea.error }
}

export default function AnalysePage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const layers = useMapLayers()
  const [mode, setMode] = useState('pincode')
  const [pincode, setPincode] = useState('')
  const [locality, setLocality] = useState(null)
  const [picked, setPicked] = useState(new Set())         // cells mode
  const [added, setAdded] = useState(new Set())           // edits on top of pincode/locality
  const [removed, setRemoved] = useState(new Set())
  const [job, setJob] = useState(null)
  const [runError, setRunError] = useState(null)

  const base = useMemo(() => {
    if (mode === 'pincode' && /^\d{6}$/.test(pincode)) return { mode, pincode }
    if (mode === 'locality' && locality) return { mode, locality_id: locality.id }
    if (mode === 'cells' && picked.size) return { mode, cells: [...picked].sort() }
    return null
  }, [mode, pincode, locality, picked])
  const selection = base && { ...base, add_cells: [...added].sort(), remove_cells: [...removed].sort() }

  const preview = useQuery({
    queryKey: ['preview', selection],
    queryFn: () => api('/areas/preview', { method: 'POST', body: selection }),
    enabled: !!selection,
    retry: false,
    placeholderData: (prev) => prev,
  })
  const shownCells = useMemo(
    () => (mode === 'cells' && !preview.data ? picked : new Set(selection ? preview.data?.select_cells ?? [] : [])),
    [mode, picked, preview.data, selection],
  )
  // Fly to an area once per new base selection (pincode/locality), not on every cell edit.
  const baseKey = JSON.stringify(base)
  const [fit, setFit] = useState(null)
  const fittedFor = useRef(null)
  useEffect(() => {
    if (mode !== 'cells' && preview.data && !preview.isPlaceholderData && fittedFor.current !== baseKey) {
      fittedFor.current = baseKey
      setFit(boundsOf(preview.data.cells_geojson))
    }
  }, [mode, baseKey, preview.data, preview.isPlaceholderData])

  const resetEdits = () => { setAdded(new Set()); setRemoved(new Set()); setJob(null); setRunError(null) }
  const switchMode = (m) => { setMode(m); resetEdits() }

  const onCellClick = (h3) => {
    setJob(null)
    if (mode === 'cells') return setPicked((s) => toggle(s, h3))
    if (!preview.data) return
    if (added.has(h3)) return setAdded((s) => toggle(s, h3))
    if (removed.has(h3)) return setRemoved((s) => toggle(s, h3))
    if (preview.data.select_cells.includes(h3)) setRemoved((s) => toggle(s, h3))
    else setAdded((s) => toggle(s, h3))
  }

  const run = async () => {
    setRunError(null)
    try {
      const res = await api('/areas/reports', { method: 'POST', body: selection })
      setJob(res.job_id)
    } catch (e) {
      setRunError(e.message)
    }
  }

  if (user?.role !== 'bd_manager') {
    return <p className="p-6">Area analysis is for the BD Manager. Switch user in the header.</p>
  }

  const p = preview.data && selection ? preview.data : null
  return (
    <div className="flex h-full flex-col md:flex-row">
      <aside className="order-2 w-full overflow-y-auto border-r border-brand/10 bg-white/70 p-4 md:order-1 md:w-[26rem]">
        <h1 className="text-lg font-bold">Analyse an area</h1>
        <div className="mt-3 flex rounded-lg bg-brand-light p-1 text-sm" role="tablist">
          {MODES.map((m) => (
            <button
              key={m.id}
              role="tab"
              aria-selected={mode === m.id}
              onClick={() => switchMode(m.id)}
              className={`flex-1 rounded-md px-2 py-1.5 ${mode === m.id ? 'bg-brand font-semibold text-white' : 'hover:bg-white'}`}
            >
              {m.label}
            </button>
          ))}
        </div>

        <div className="mt-4">
          {mode === 'pincode' && (
            <input
              value={pincode}
              onChange={(e) => { setPincode(e.target.value.replace(/\D/g, '').slice(0, 6)); resetEdits() }}
              placeholder="6-digit pincode, e.g. 600017"
              inputMode="numeric"
              className="w-full rounded border px-3 py-2"
              aria-label="Pincode"
            />
          )}
          {mode === 'locality' && (
            locality ? (
              <div className="flex items-center justify-between rounded border bg-white px-3 py-2 text-sm">
                <span><strong>{locality.name}</strong> <span className="opacity-60">({locality.kind.replace('_', ' ')})</span></span>
                <button onClick={() => { setLocality(null); resetEdits() }} className="text-brand underline">change</button>
              </div>
            ) : (
              <LocalitySearch onPick={(c) => { setLocality(c); resetEdits() }} />
            )
          )}
          {mode === 'cells' && (
            <p className="text-sm">
              Click cells on the map to select them ({picked.size} selected).
              {picked.size > 0 && <button onClick={() => { setPicked(new Set()); resetEdits() }} className="ml-2 text-brand underline">clear</button>}
            </p>
          )}
        </div>

        {preview.isError && selection && (
          <p className="mt-3 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-800">{preview.error.message}</p>
        )}
        {p && (
          <section className="mt-4 rounded-lg border border-brand/20 bg-white p-3 text-sm">
            <h2 className="font-semibold">{p.label}</h2>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
              <dt className="opacity-60">Area</dt><dd>{p.area_km2} km² · {p.select_cells.length} cells</dd>
              <dt className="opacity-60">Boundary</dt>
              <dd className={p.basis.approximate ? 'text-amber-700' : ''}>{p.basis.label}</dd>
            </dl>
            {p.warnings.map((w) => <p key={w} className="mt-2 text-amber-700">⚠ {w}</p>)}
            {mode !== 'cells' && (
              <p className="mt-2 opacity-70">
                Click map cells to add or remove them{(added.size || removed.size) ? ` (+${added.size} / −${removed.size})` : ''}.
                {(added.size > 0 || removed.size > 0) && <button onClick={resetEdits} className="ml-1 text-brand underline">undo edits</button>}
              </p>
            )}
            {p.previous_reports.length > 0 && (
              <p className="mt-2">
                Analysed before:{' '}
                {p.previous_reports.slice(0, 3).map((r) => (
                  <Link key={r.id} to={`/areas/reports/${r.id}`} className="mr-2 text-brand underline">
                    v{r.version} ({r.score ?? r.status})
                  </Link>
                ))}
              </p>
            )}
            {!job && (
              <button onClick={run} className="mt-3 w-full rounded-md bg-accent px-4 py-2 font-semibold text-ink shadow hover:brightness-95">
                {p.previous_reports.length ? `Run again (v${p.previous_reports[0].version + 1})` : 'Run analysis'}
              </button>
            )}
            {runError && <p className="mt-2 text-red-700">{runError}</p>}
          </section>
        )}
        {job && (
          <div className="mt-4">
            <JobProgress jobId={job} onSucceeded={(out) => out.report_id && navigate(`/areas/reports/${out.report_id}`)} />
          </div>
        )}
        {layers.error && <p className="mt-3 text-sm text-red-700">Map data unavailable: {layers.error.message}</p>}
        <p className="mt-6 text-xs opacity-60">
          Grey cells are mostly water, airport, industrial or empty land — they are shown but not scored.
          Yellow dots are existing Savomart stores.
        </p>
      </aside>
      <div className="order-1 h-72 md:order-2 md:h-auto md:flex-1">
        <MapView {...layers} selected={shownCells} onCellClick={onCellClick} fit={fit} />
      </div>
    </div>
  )
}
