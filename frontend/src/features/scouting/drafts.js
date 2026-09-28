// Property drafts saved on the phone (per user). A draft keeps its client_id, so submitting it again
// after a failed attempt can never create a second property (the API dedupes on client_id).
const key = (userId) => `sitescout.drafts.${userId}`

function read(userId) {
  try {
    return JSON.parse(localStorage.getItem(key(userId))) ?? {}
  } catch {
    return {}
  }
}

function write(userId, drafts) {
  try {
    localStorage.setItem(key(userId), JSON.stringify(drafts))
  } catch {
    /* storage full or blocked: the form still works, it just won't survive a reload */
  }
}

export const listDrafts = (userId) =>
  Object.values(read(userId)).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))

export const getDraft = (userId, clientId) => read(userId)[clientId] ?? null

export function saveDraft(userId, draft) {
  write(userId, { ...read(userId), [draft.clientId]: { ...draft, updatedAt: new Date().toISOString() } })
}

export function deleteDraft(userId, clientId) {
  const drafts = read(userId)
  delete drafts[clientId]
  write(userId, drafts)
}
