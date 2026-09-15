import { useEffect, useState } from 'react'
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
  apply_ready: { can_spawn: boolean; host_watcher: boolean; repo_dir: string }
  status: { state: string; tag?: string | null; message?: string; requested_at?: string | null }
}

export default function Updates() {
  const role = currentUser()?.role
  const [data, setData] = useState<Catalog | null>(null)
  const [selected, setSelected] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    try {
      const catalog = await api<Catalog>('/api/admin/updates')
      setData(catalog)
      setSelected((current) => current || catalog.builds.find((b) => b.is_latest && !b.is_current)?.tag || catalog.builds[0]?.tag || '')
      setErr('')
    } catch (e: any) {
      setErr(e.message || 'Could not load builds')
    }
  }

  useEffect(() => {
    if (role === 'ADMIN') void load()
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

  async function apply() {
    if (!selected) return
    setBusy(true)
    try {
      await api('/api/admin/updates/apply', { method: 'POST', body: JSON.stringify({ tag: selected }) })
      await load()
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (role !== 'ADMIN') return <p className="err">Administrator role required.</p>
  if (!data && !err) return <p className="muted">Loading GitHub builds…</p>
  const chosen = data?.builds.find((b) => b.tag === selected)
  const applying = data?.status?.state === 'queued' || data?.status?.state === 'running'
  const actionLabel = chosen?.action === 'downgrade' ? 'Downgrade' : chosen?.action === 'current' ? 'Reinstall' : 'Update'

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Server updates</h2>
          <p>Last 3 GitHub releases. Select a build to update or downgrade this server.</p>
        </div>
        <button className="btn secondary" onClick={load} disabled={busy}>Refresh</button>
      </div>

      {err && <p className="err">{err}</p>}
      {data?.source_error && data.source !== 'github' && (
        <p className="err">GitHub list unavailable ({data.source}). {data.source_error}</p>
      )}

      {data && (
        <div className="grid stats" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', marginBottom: 16 }}>
          <div className="card stat"><div className="label">Current</div><div className="value">{data.current.tag}</div></div>
          <div className="card stat online"><div className="label">Latest</div><div className="value">{data.latest?.tag || '—'}</div></div>
          <div className="card stat"><div className="label">Source</div><div className="value" style={{ fontSize: 18 }}>{data.github_repo}</div></div>
        </div>
      )}

      {data?.status?.state && data.status.state !== 'idle' && (
        <div className="card" style={{ marginBottom: 16 }}>
          <strong className={`badge ${data.status.state === 'ok' ? 'ONLINE' : data.status.state === 'error' ? 'OFFLINE' : 'WARNING'}`}>
            {data.status.state}
          </strong>
          <span style={{ marginLeft: 10 }}>{data.status.message}</span>
          {data.status.requested_at && <div className="muted">{ago(data.status.requested_at)}</div>}
        </div>
      )}

      <div className="build-grid">
        {(data?.builds || []).map((b) => (
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

      {data && data.builds.length === 0 && (
        <p className="muted">No GitHub releases found yet. Push a tagged release to {data.github_url}</p>
      )}

      <div className="card toolbar" style={{ marginTop: 16, alignItems: 'center' }}>
        <span className="muted">Selected {selected || '—'}</span>
        <button className="btn" disabled={!chosen || busy || applying} onClick={apply}>
          {busy || applying ? 'Working…' : `${actionLabel} to ${selected || 'build'}`}
        </button>
      </div>
      {data && !data.apply_ready.can_spawn && !data.apply_ready.host_watcher && (
        <p className="muted">
          Apply backend is not mounted. On the server run <code>sudo ./scripts/linux/install-host-updater.sh</code>
          {' '}or start Compose so the API can see <code>/var/run/docker.sock</code> and the git checkout.
        </p>
      )}
    </>
  )
}
