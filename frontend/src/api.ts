export type Role = 'ADMIN' | 'OPERATOR' | 'VIEWER'

const TOKEN = 'lw_access'
const REFRESH = 'lw_refresh'
const USER = 'lw_user'

export function getToken() {
  return localStorage.getItem(TOKEN)
}

export function currentUser(): { username: string; role: Role; user_id: string } | null {
  const raw = localStorage.getItem(USER)
  return raw ? JSON.parse(raw) : null
}

export function setSession(data: { access_token: string; refresh_token: string; username: string; role: Role; user_id: string }) {
  localStorage.setItem(TOKEN, data.access_token)
  localStorage.setItem(REFRESH, data.refresh_token)
  localStorage.setItem(USER, JSON.stringify({ username: data.username, role: data.role, user_id: data.user_id }))
}

export function clearSession() {
  localStorage.removeItem(TOKEN)
  localStorage.removeItem(REFRESH)
  localStorage.removeItem(USER)
}

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (!headers.has('Content-Type') && init.body) headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(path, { ...init, headers })
  if (res.status === 401) {
    clearSession()
    if (!path.includes('/api/auth/login')) window.location.href = '/login'
    throw new Error('Unauthorized')
  }
  if (res.status === 502 || res.status === 503 || res.status === 504) {
    throw new Error(
      'API is down (Bad Gateway). On the server run: sudo docker compose ps && sudo docker compose logs api --tail 80',
    )
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export function bytes(n?: number | null) {
  if (n === null || n === undefined) return 'Unknown / Not reported'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

export function ago(iso?: string | null) {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  const s = Math.max(0, (Date.now() - then) / 1000)
  if (s < 60) return `${Math.floor(s)}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export function fmt(v: unknown) {
  if (v === null || v === undefined || v === '') return 'Unknown / Not reported'
  return String(v)
}
