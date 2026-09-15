import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ago, api, currentUser } from '../api'

type Build = {
  tag: string
  name: string
  published_at?: string | null
  html_url?: string
  notes?: string
  is_current: boolean
  is_latest: boolean
  action: 'update' | 'downgrade' | 'current' | 'reinstall'
}

type Catalog = {
  enabled: boolean
  github_repo: string
  github_url: string
  current: { version: string; tag: string; in_catalog: boolean }
  latest: { tag: string; name: string } | null
  builds: Build[]
  source: string
  source_error?: string | null
  needs_fetch?: boolean
  apply_ready: { can_spawn: boolean; host_watcher: boolean; repo_dir: string }
  status: { state: string; tag?: string | null; message?: string; requested_at?: string | null }
}

export default function Updates() {
  const role = currentUser()?.role
  const [meta, setMeta] = useState<Catalog | null>(null)
  const [data, setData] = useState<Catalog | null>(null)
  const [proxyUser, setProxyUser] = useState('')
  const [proxyPassword, setProxyPassword] = useState('')
  const [selected, setSelected] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function loadMeta() {
    try {
      const catalog = await api<Catalog>('/api/admin/updates')
      setMeta(catalog)
      setErr('')
    } catch (e: any) {
      setErr(e.message || 'Could not load update status')
    }
  }

  useEffect(() => {
    if (role === 'ADMIN') void loadMeta()
  }, [role])

  useEffect(() => {
    const active = data?.status?.state === 'queued' || data?.status?.state === 'running'
    if (!active) return
    const id = window.setInterval(() => {
      api('/api/admin/updates/status')
        .then((row) => setData((prev) => (prev ? { ...prev, status: row.status } : prev)))
        .catch(() => setData((prev) => (prev ? { ...prev, status: { ...prev.status, message: 'API restarting after rebuild…' } } : prev)))
    }, 2500)
    return () => window.clearInterval(id)
  }, [data?.status?.state])

  async function fetchBuilds(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      const catalog = await api<Catalog>('/api/admin/updates/fetch', {
        method: 'POST',
        body: JSON.stringify({ proxy_user: proxyUser, proxy_password: proxyPassword }),
      })
      setData(catalog)
      setMeta(catalog)
      setSelected(catalog.builds.find((b) => b.is_latest && !b.is_current)?.tag || catalog.builds[0]?.tag || '')
      if (catalog.source !== 'github') {
        setErr(catalog.source_error || 'GitHub fetch failed')
      }
    } catch (e: any) {
      setData(null)
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function apply() {
    if (!selected) return
    setBusy(true)
    try {
      await api('/api/admin/updates/apply', { method: 'POST', body: JSON.stringify({ tag: selected }) })
      const catalog = await api<Catalog>('/api/admin/updates/status')
      setData((prev) => (prev ? { ...prev, status: catalog.status } : prev))
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (role !== 'ADMIN') return <p className="err">Administrator role required.</p>
  const shown = data?.source === 'github' ? data : null
  const chosen = shown?.builds.find((b) => b.tag === selected)
  const applying = shown?.status?.state === 'queued' || shown?.status?.state === 'running'
  const actionLabel = chosen?.action === 'downgrade' ? 'Downgrade' : chosen?.action === 'current' ? 'Reinstall' : 'Update'
  const currentTag = shown?.current.tag || meta?.current.tag

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Server updates</h2>
          <p>Enter campus proxy credentials, then fetch GitHub releases. Builds stay hidden until fetch succeeds.</p>
        </div>
      </div>

      <div className="grid stats" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', marginBottom: 16 }}>
        <div className="card stat"><div className="label">Current</div><div className="value">{currentTag || '—'}</div></div>
        <div className="card stat"><div className="label">Source</div><div className="value" style={{ fontSize: 18 }}>{meta?.github_repo || 'karpus2807/iitd_lab'}</div></div>
      </div>

      <form className="card toolbar" onSubmit={fetchBuilds} style={{ marginBottom: 16, alignItems: 'center' }}>
        <input
          placeholder="Proxy username"
          value={proxyUser}
          autoComplete="username"
          onChange={(e) => setProxyUser(e.target.value)}
          required
        />
        <input
          placeholder="Proxy password"
          type="password"
          value={proxyPassword}
          autoComplete="current-password"
          onChange={(e) => setProxyPassword(e.target.value)}
          required
        />
        <button className="btn" disabled={busy}>{busy ? 'Fetching…' : 'Fetch GitHub releases'}</button>
      </form>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Used only to reach GitHub through the campus proxy. Credentials are not stored.
      </p>

      {err && <p className="err">{err}</p>}

      {shown?.status?.state && shown.status.state !== 'idle' && (
        <div className="card" style={{ marginBottom: 16 }}>
          <strong className={`badge ${shown.status.state === 'ok' ? 'ONLINE' : shown.status.state === 'error' ? 'OFFLINE' : 'WARNING'}`}>
            {shown.status.state}
          </strong>
          <span style={{ marginLeft: 10 }}>{shown.status.message}</span>
          {shown.status.requested_at && <div className="muted">{ago(shown.status.requested_at)}</div>}
        </div>
      )}

      {!shown && !err && (
        <p className="muted">Releases appear here after a successful fetch.</p>
      )}

      {shown && (
        <>
          <div className="grid stats" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', marginBottom: 16 }}>
            <div className="card stat"><div className="label">Current</div><div className="value">{shown.current.tag}</div></div>
            <div className="card stat online"><div className="label">Latest</div><div className="value">{shown.latest?.tag || '—'}</div></div>
            <div className="card stat"><div className="label">Fetched</div><div className="value" style={{ fontSize: 18 }}>{shown.source}</div></div>
          </div>

          <div className="build-grid">
            {shown.builds.map((b) => (
              <button
                key={b.tag}
                type="button"
                className={`card build-card${selected === b.tag ? ' selected' : ''}${b.is_current ? ' current' : ''}`}
                onClick={() => setSelected(b.tag)}
              >
                <div className="build-card-head">
                  <strong className="mono">{b.tag}</strong>
                  <span>
                    {b.is_current && <span className="badge ONLINE">Current</span>}
                    {b.is_latest && <span className="badge INFO">Latest</span>}
                  </span>
                </div>
                <div>{b.name}</div>
                <div className="muted">{b.published_at ? ago(b.published_at) : 'release date unknown'}</div>
                {b.notes && <p className="muted build-notes">{b.notes.slice(0, 180)}{b.notes.length > 180 ? '…' : ''}</p>}
              </button>
            ))}
          </div>

          {shown.builds.length === 0 && (
            <p className="muted">No GitHub releases found yet. Push a tagged release to {shown.github_url}</p>
          )}

          <div className="card toolbar" style={{ marginTop: 16, alignItems: 'center' }}>
            <span className="muted">Selected {selected || '—'}</span>
            <button className="btn" disabled={!chosen || busy || applying} onClick={apply}>
              {busy || applying ? 'Working…' : `${actionLabel} to ${selected || 'build'}`}
            </button>
          </div>
          {!shown.apply_ready.can_spawn && !shown.apply_ready.host_watcher && (
            <p className="muted">
              Apply backend is not mounted. On the server run <code>sudo ./scripts/linux/install-host-updater.sh</code>
              {' '}or start Compose so the API can see <code>/var/run/docker.sock</code> and the git checkout.
            </p>
          )}
        </>
      )}
    </>
  )
}
