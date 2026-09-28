// Map overlays for a saved report: per-cell score heat (res-9 cells drawn client-side with h3-js),
// the analysed area's outline, and numbered hotspots.
import { cellToBoundary } from 'h3-js'

const polygon = (h3) => {
  const ring = cellToBoundary(h3, true) // [lng, lat]
  return { type: 'Polygon', coordinates: [[...ring, ring[0]]] }
}

export function reportOverlays(report, { idPrefix = 'r', color = '#782b90', heat = true } = {}) {
  const overlays = [
    {
      id: `${idPrefix}-area`,
      data: report.cells_geojson,
      layers: [
        { id: `${idPrefix}-area-line`, type: 'line', paint: { 'line-color': color, 'line-width': 2 }, beforeId: 'stores' },
      ],
    },
  ]
  if (heat) {
    overlays.unshift({
      id: `${idPrefix}-heat`,
      data: {
        type: 'FeatureCollection',
        features: Object.entries(report.result.cell_scores ?? {}).map(([h3, score]) => ({
          type: 'Feature', properties: { h3, score }, geometry: polygon(h3),
        })),
      },
      layers: [{
        id: `${idPrefix}-heat-fill`, type: 'fill', beforeId: 'stores',
        paint: {
          'fill-color': ['interpolate', ['linear'], ['get', 'score'], 30, '#f3e9f6', 50, '#c79bd6', 70, '#782b90', 85, '#3d1049'],
          'fill-opacity': 0.72,
        },
      }],
    })
    overlays.push({
      id: `${idPrefix}-hotspots`,
      data: {
        type: 'FeatureCollection',
        features: report.result.hotspots.map((h, i) => ({
          type: 'Feature', properties: { rank: String(i + 1), h3: h.h3 },
          geometry: { type: 'Point', coordinates: [h.lon, h.lat] },
        })),
      },
      layers: [
        { id: `${idPrefix}-hotspot-dot`, type: 'circle',
          paint: { 'circle-radius': 11, 'circle-color': '#fff200', 'circle-stroke-color': '#1c1022', 'circle-stroke-width': 2 } },
        { id: `${idPrefix}-hotspot-num`, type: 'symbol',
          layout: { 'text-field': ['get', 'rank'], 'text-font': ['Noto Sans Bold'], 'text-size': 12, 'text-allow-overlap': true },
          paint: { 'text-color': '#1c1022' } },
      ],
    })
  }
  return overlays
}
