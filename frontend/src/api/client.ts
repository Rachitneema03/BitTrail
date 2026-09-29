const BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '') + '/api/v1'
const TOKEN_KEY = 'bittrail.token'

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}
export function setToken(t: string | null) {
  try { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY) } catch { /* private mode */ }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const t = getToken()
  if (t) headers.set('Authorization', `Bearer ${t}`)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const r = await fetch(BASE + path, { ...init, headers })
  if (r.status === 401) { setToken(null); if (!location.pathname.startsWith('/login')) location.href = '/login' }
  if (!r.ok) {
    let msg = r.statusText
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* not json */ }
    throw new ApiError(r.status, msg)
  }
  return r.json() as Promise<T>
}

export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

/** Open an authenticated PDF in a new tab. */
export async function openPdf(reportId: string) {
  const r = await fetch(`${BASE}/reports/${reportId}.pdf`, { headers: { Authorization: `Bearer ${getToken()}` } })
  if (!r.ok) throw new ApiError(r.status, 'Could not load PDF')
  const url = URL.createObjectURL(await r.blob())
  window.open(url, '_blank')
}
