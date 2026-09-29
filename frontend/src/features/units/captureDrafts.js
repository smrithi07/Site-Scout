// Lane-capture drafts on this phone (Core rule 6): every change is kept locally, and the draft's
// client id + capture time are fixed when it is first saved, so re-sending after a failed network
// call is the same submission (the API answers 200 with the saved capture). A draft is removed only
// after the API has confirmed it.
const PREFIX = 'sitescout.capture.'
const key = (userId, unitId, segmentId) => `${PREFIX}${userId}.${unitId}.${segmentId}`

function read(k) {
  try { return JSON.parse(localStorage.getItem(k)) } catch { return null }
}

export function loadDraft(userId, unitId, segmentId) {
  return read(key(userId, unitId, segmentId))
}

export function saveDraft(userId, unitId, segmentId, draft) {
  try { localStorage.setItem(key(userId, unitId, segmentId), JSON.stringify({ ...draft, segment_id: segmentId, updated_at: new Date().toISOString() })) } catch { /* storage full or blocked */ }
}

export function clearDraft(userId, unitId, segmentId) {
  try { localStorage.removeItem(key(userId, unitId, segmentId)) } catch { /* ignore */ }
}

/** Drafts for a unit that were submitted but not confirmed (no network) — shown as "waiting to send". */
export function queuedDrafts(userId, unitId) {
  const out = []
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (!k?.startsWith(`${PREFIX}${userId}.${unitId}.`)) continue
      const d = read(k)
      if (d?.queued) out.push(d)
    }
  } catch { /* ignore */ }
  return out
}

/** Build the API body from a draft (the same body every time it is re-sent). */
export function captureBody(unitId, segmentId, d) {
  return {
    client_id: d.client_id, unit_id: Number(unitId), segment_id: segmentId, status: d.status,
    reason: d.status === 'could_not_survey' ? d.reason : null,
    observations: d.status === 'surveyed' ? d.obs : null,
    lat: d.gps.lat, lon: d.gps.lon, gps_accuracy_m: d.gps.accuracy ?? null,
    captured_at: d.captured_at, notes: d.notes || null,
  }
}

export const isNetworkError = (e) => e instanceof TypeError   // fetch rejects with TypeError when offline
