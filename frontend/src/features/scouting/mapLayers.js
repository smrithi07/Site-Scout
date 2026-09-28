// Map overlays for scouting: a task's area + hotspots, scouted properties, and the form's pin.
import { cellToBoundary } from 'h3-js'

const cellPolygon = (h3) => {
  const ring = cellToBoundary(h3, true)
  return { type: 'Polygon', coordinates: [[...ring, ring[0]]] }
}
const point = (lon, lat, properties = {}) => ({ type: 'Feature', properties, geometry: { type: 'Point', coordinates: [lon, lat] } })

export function taskOverlays(task, prefix = 'task') {
  return [
    {
      id: `${prefix}-area`,
      data: { type: 'FeatureCollection', features: task.target_cells.map((h) => ({ type: 'Feature', properties: {}, geometry: cellPolygon(h) })) },
      layers: [
        { id: `${prefix}-area-fill`, type: 'fill', paint: { 'fill-color': '#782b90', 'fill-opacity': 0.12 }, beforeId: 'stores' },
        { id: `${prefix}-area-line`, type: 'line', paint: { 'line-color': '#782b90', 'line-width': 1.5 }, beforeId: 'stores' },
      ],
    },
    {
      id: `${prefix}-hotspots`,
      data: { type: 'FeatureCollection', features: task.hotspots.map((h, i) => point(h.lon, h.lat, { rank: String(i + 1) })) },
      layers: [
        { id: `${prefix}-hs-dot`, type: 'circle', paint: { 'circle-radius': 11, 'circle-color': '#fff200', 'circle-stroke-color': '#1c1022', 'circle-stroke-width': 2 } },
        { id: `${prefix}-hs-num`, type: 'symbol', layout: { 'text-field': ['get', 'rank'], 'text-font': ['Noto Sans Bold'], 'text-size': 12, 'text-allow-overlap': true }, paint: { 'text-color': '#1c1022' } },
      ],
    },
    ...propertyOverlays(task.properties, `${prefix}-props`),
  ]
}

export function propertyOverlays(properties, id = 'props') {
  return [{
    id,
    data: { type: 'FeatureCollection', features: properties.map((p) => point(p.lon, p.lat, { label: p.label })) },
    layers: [
      { id: `${id}-dot`, type: 'circle', paint: { 'circle-radius': 7, 'circle-color': '#782b90', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2 } },
      { id: `${id}-label`, type: 'symbol', minzoom: 14, layout: { 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Regular'], 'text-size': 11, 'text-offset': [0, 1.2], 'text-anchor': 'top' },
        paint: { 'text-color': '#1c1022', 'text-halo-color': '#ffffff', 'text-halo-width': 1.5 } },
    ],
  }]
}

export function pinOverlay(lat, lon, accuracyM) {
  return [{
    id: 'pin',
    data: { type: 'FeatureCollection', features: [point(lon, lat)] },
    layers: [
      ...(accuracyM ? [{ id: 'pin-acc', type: 'circle', paint: {
        // approximate metres → pixels at the current zoom (≈ 2^z / 156543 px per metre at the equator)
        'circle-radius': ['interpolate', ['exponential', 2], ['zoom'], 10, accuracyM / 150, 20, accuracyM * 6.7],
        'circle-color': '#782b90', 'circle-opacity': 0.12 } }] : []),
      { id: 'pin-dot', type: 'circle', paint: { 'circle-radius': 9, 'circle-color': '#e11d48', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 3 } },
    ],
  }]
}
