// MapLibre map of the service area. Base map: OpenFreeMap (free, no key) — the only thing the
// browser fetches from outside; everything analytical comes from our API.
import { Map as MapLibreMap, NavigationControl } from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'

const STYLE = 'https://tiles.openfreemap.org/styles/positron'
const BRAND = '#782b90'
const CHENNAI = [80.235, 13.05]

export function boundsOf(geojson) {
  let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity]
  const walk = (c) => {
    if (typeof c[0] === 'number') {
      minX = Math.min(minX, c[0]); minY = Math.min(minY, c[1])
      maxX = Math.max(maxX, c[0]); maxY = Math.max(maxY, c[1])
    } else c.forEach(walk)
  }
  ;(geojson.features ?? [geojson]).forEach((f) => walk(f.geometry.coordinates))
  return Number.isFinite(minX) ? [[minX, minY], [maxX, maxY]] : null
}

/**
 * grid: FeatureCollection of selection cells (properties.h3, scoreable_share)
 * selected: Set of h3 ids to highlight; onCellClick(h3) makes the grid clickable
 * fit: bounds to fly to when it changes; overlays: [{id, data, layers}] extra sources (5b)
 */
export default function MapView({ grid, serviceArea, stores, selected, onCellClick, onMapClick, fit, overlays = [] }) {
  const container = useRef(null)
  const map = useRef(null)
  const shown = useRef(new Set())
  const clickRef = useRef(onCellClick)
  const mapClickRef = useRef(onMapClick)
  const [ready, setReady] = useState(false)
  clickRef.current = onCellClick
  mapClickRef.current = onMapClick

  useEffect(() => {
    const m = new MapLibreMap({ container: container.current, style: STYLE, center: CHENNAI, zoom: 10.5,
                                   attributionControl: { compact: true } })
    m.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    m.on('load', () => {
      m.addSource('grid', { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, promoteId: 'h3' })
      m.addLayer({ id: 'grid-fill', type: 'fill', source: 'grid', paint: {
        'fill-color': ['case', ['boolean', ['feature-state', 'selected'], false], BRAND,
                      ['<', ['get', 'scoreable_share'], 0.3], '#8a8a8a', BRAND],
        'fill-opacity': ['case', ['boolean', ['feature-state', 'selected'], false], 0.42,
                         ['<', ['get', 'scoreable_share'], 0.3], 0.28,
                         ['boolean', ['feature-state', 'hover'], false], 0.14, 0.02],
      } })
      m.addLayer({ id: 'grid-line', type: 'line', source: 'grid',
                   paint: { 'line-color': BRAND, 'line-opacity': 0.22, 'line-width': 0.6 } })
      m.addSource('service-area', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      m.addLayer({ id: 'service-area', type: 'line', source: 'service-area',
                   paint: { 'line-color': BRAND, 'line-width': 2, 'line-opacity': 0.8 } })
      m.addSource('stores', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      m.addLayer({ id: 'stores', type: 'circle', source: 'stores', paint: {
        'circle-radius': 6, 'circle-color': '#fff200', 'circle-stroke-color': '#1c1022', 'circle-stroke-width': 1.5 } })
      m.addLayer({ id: 'store-labels', type: 'symbol', source: 'stores', minzoom: 11.5, layout: {
        'text-field': ['concat', 'Savomart · ', ['get', 'name']], 'text-font': ['Noto Sans Regular'],
        'text-size': 11, 'text-offset': [0, 1.2], 'text-anchor': 'top' },
        paint: { 'text-color': '#1c1022', 'text-halo-color': '#ffffff', 'text-halo-width': 1.5 } })

      let hovered = null
      m.on('mousemove', 'grid-fill', (e) => {
        if (!clickRef.current) return
        m.getCanvas().style.cursor = 'pointer'
        const id = e.features[0]?.id
        if (hovered !== id) {
          if (hovered) m.setFeatureState({ source: 'grid', id: hovered }, { hover: false })
          hovered = id
          m.setFeatureState({ source: 'grid', id }, { hover: true })
        }
      })
      m.on('mouseleave', 'grid-fill', () => {
        m.getCanvas().style.cursor = ''
        if (hovered) m.setFeatureState({ source: 'grid', id: hovered }, { hover: false })
        hovered = null
      })
      m.on('click', 'grid-fill', (e) => clickRef.current?.(e.features[0]?.properties.h3))
      m.on('click', (e) => mapClickRef.current?.({ lat: e.lngLat.lat, lon: e.lngLat.lng }))
      setReady(true)
    })
    map.current = m
    return () => m.remove()
  }, [])

  useEffect(() => { if (ready && grid) map.current.getSource('grid').setData(grid) }, [ready, grid])
  useEffect(() => {
    if (!ready || !serviceArea) return
    map.current.getSource('service-area').setData(serviceArea)
    if (!fit) map.current.fitBounds(boundsOf(serviceArea), { padding: 30, duration: 0 }) // frame GCC on first load
  }, [ready, serviceArea]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (ready && stores) map.current.getSource('stores').setData(stores) }, [ready, stores])

  // Selection highlight via feature-state: only the cells that changed are touched.
  useEffect(() => {
    if (!ready || !grid) return
    const next = selected ?? new Set()
    for (const id of shown.current) if (!next.has(id)) map.current.setFeatureState({ source: 'grid', id }, { selected: false })
    for (const id of next) if (!shown.current.has(id)) map.current.setFeatureState({ source: 'grid', id }, { selected: true })
    shown.current = new Set(next)
  }, [ready, grid, selected])

  useEffect(() => {
    if (ready && fit) map.current.fitBounds(fit, { padding: 60, maxZoom: 14, duration: 600 })
  }, [ready, fit])

  // Extra overlays (report hotspots, cell scores): added/updated by id, removed when gone.
  useEffect(() => {
    if (!ready) return
    const m = map.current
    for (const o of overlays) {
      if (m.getSource(o.id)) m.getSource(o.id).setData(o.data)
      else {
        m.addSource(o.id, { type: 'geojson', data: o.data })
        o.layers.forEach((layer) => m.addLayer({ ...layer, source: o.id }, layer.beforeId))
      }
    }
    return () => {
      for (const o of overlays) {
        o.layers.forEach((layer) => m.getLayer(layer.id) && m.removeLayer(layer.id))
        if (m.getSource(o.id)) m.removeSource(o.id)
      }
    }
  }, [ready, overlays])

  return <div ref={container} className="h-full w-full" />
}
