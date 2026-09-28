// Thin fetch wrapper: bearer token, JSON in/out, and errors that carry the API's own message
// (403 role checks, 422 selection problems, 409 conflicts) so the UI can show them verbatim.
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const SESSION_KEY = 'sitescout.session'

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail))
    this.status = status
    this.detail = detail
  }
}

export function loadSession() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY)) ?? null
  } catch {
    return null
  }
}

export function saveSession(session) {
  try {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session))
    else localStorage.removeItem(SESSION_KEY)
  } catch {
    /* private mode: the session just won't survive a reload */
  }
}

let onUnauthorized = () => {}
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

export async function api(path, { method = 'GET', body, token } = {}) {
  const session = loadSession()
  const bearer = token ?? session?.token
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401 && !token) onUnauthorized()
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : await res.text()
  if (!res.ok) {
    const detail = data?.detail ?? data
    // FastAPI validation errors arrive as a list of {msg, loc}; flatten to one readable line.
    const message = Array.isArray(detail) ? detail.map((d) => d.msg).join('; ') : detail
    throw new ApiError(res.status, message)
  }
  return data
}
