import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ago, api, currentUser } from '../api'
import ProgressPanel from '../components/ProgressPanel'

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

type UpdateStatus = {
  state: string
  tag?: string | null
  message?: string
  requested_at?: string | null
  progress?: number | null
  step?: string
  log?: string
  log_tail?: string
  stuck?: boolean
  can_cancel?: boolean
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
  proxy_required?: boolean
  used_proxy?: boolean
  direct_ok?: boolean
  apply_ready: { can_spawn: boolean; host_watcher: boolean; repo_dir: string }
  status: UpdateStatus
}

export default function Updates() {
  const role = currentUser()?.role
  const [data, setData] = useState<Catalog | null>(null)
  const [proxyUser, setProxyUser] = useState('')
  const [proxyPassword, setProxyPassword] = useState('')
  const [selected, setSelected] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [fetchProgress, setFetchProgress] = useState<number | null>(null)

  function applyCatalog(catalog: Catalog) {
    setData(catalog)
    if (catalog.builds.length) {
      setSelected(catalog.builds.find((b) => b.is_latest && !b.is_current)?.tag || catalog.builds[0]?.tag || '')
    }
    if (catalog.source === 'github') {
      setErr('')
    } else if (catalog.source_error) {
      setErr(catalog.source_error)
    }
  }

  async function loadCatalog() {
    setLoading(true)
    try {
      const catalog = await api<Catalog>('/api/admin/updates')
      applyCatalog(catalog)
    } catch (e: any) {
      setErr(e.message || 'Could not load update status')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (role === 'ADMIN') void loadCatalog()
  }, [role])

  const st = data?.status
  const applyActive = st?.state === 'queued' || st?.state === 'running'
  const applyStuck = Boolean(st?.stuck)
  const canCancel = Boolean(st?.can_cancel) || applyActive

  useEffect(() => {
    if (!applyActive && !applyStuck) return
    const tick = () => {
      api<{ status: UpdateStatus }>('/api/admin/updates/status')
        .then((row) => setData((prev) => (prev ? { ...prev, status: row.status } : prev)))
        .catch(() =>
          setData((prev) =>
            prev
              ? {
                  ...prev,
                  status: {
                    ...prev.status,
                    message: 'API restarting after rebuild…',
                    progress: prev.status.progress != null ? Math.min(95, Number(prev.status.progress) || 70) : 70,
                    step: 'restart',
                  },
                }
              : prev,
          ),
        )
    }
    tick()
    const id = window.setInterval(tick, 1000)
    return () => window.clearInterval(id)
  }, [applyActive, applyStuck])

  async function fetchBuilds(e: FormEvent) {
    e.preventDefault()
    if (!proxyRequired) return
    setBusy(true)
    setErr('')
    setFetchProgress(15)
    const bump = window.setInterval(() => {
      setFetchProgress((p) => (p == null || p >= 85 ? p : p + 8))
    }, 400)
    try {
      const catalog = await api<Catalog>('/api/admin/updates/fetch', {
        method: 'POST',
        body: JSON.stringify({ proxy_user: proxyUser, proxy_password: proxyPassword }),
      })
      setFetchProgress(100)
      applyCatalog(catalog)
      if (catalog.source !== 'github') {
        setErr(catalog.source_error || 'GitHub fetch failed')
      }
    } catch (e: any) {
      setErr(e.message)
      setFetchProgress(null)
    } finally {
      window.clearInterval(bump)
      setBusy(false)
      window.setTimeout(() => setFetchProgress(null), 800)
    }
  }

  async function apply(force = false) {
    if (!selected) return
    setBusy(true)
    setErr('')
    try {
      await api('/api/admin/updates/apply', {
        method: 'POST',
        body: JSON.stringify({ tag: selected, force }),
      })
      const catalog = await api<{ status: UpdateStatus }>('/api/admin/updates/status')
      setData((prev) => (prev ? { ...prev, status: catalog.status } : prev))
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function cancelApply() {
    setBusy(true)
    setErr('')
    try {
      const row = await api<{ status: UpdateStatus }>('/api/admin/updates/cancel', {
        method: 'POST',
        body: JSON.stringify({ reason: 'Cancelled from Updates UI' }),
      })
      setData((prev) => (prev ? { ...prev, status: row.status } : prev))
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (role !== 'ADMIN') return <p className="err">Administrator role required.</p>

  const proxyRequired = Boolean(data?.proxy_required)
  const shown = data && (data.source === 'github' || (data.source === 'cache' && data.builds.length > 0)) ? data : null
  const chosen = shown?.builds.find((b) => b.tag === selected)
  const actionLabel = chosen?.action === 'downgrade' ? 'Downgrade' : chosen?.action === 'current' ? 'Reinstall' : 'Update'
  const currentTag = data?.current.tag
  const applyBlocked = applyActive && !applyStuck
  const progressError = st?.state === 'error' || st?.state === 'cancelled' || applyStuck

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Server updates</h2>
          <p>
            Releases load automatically when GitHub is reachable. On campus proxy networks, enter credentials and fetch.
            Stuck installs auto-reset; you can also Cancel and re-run.
          </p>
        </div>
      </div>

      <div className="grid stats" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', marginBottom: 16 }}>
        <div className="card stat"><div className="label">Current</div><div className="value">{currentTag || '—'}</div></div>
        <div className="card stat"><div className="label">Source</div><div className="value" style={{ fontSize: 18 }}>{data?.github_repo || 'karpus2807/iitd_lab'}</div></div>
      </div>

      {loading && <p className="muted">Fetching GitHub releases…</p>}

      {!loading && data?.direct_ok && (
        <p className="muted" style={{ marginBottom: 16 }}>
          GitHub reached directly — proxy credentials are not needed. Fetch button is disabled.
        </p>
      )}

      <form className="card toolbar" onSubmit={fetchBuilds} style={{ marginBottom: 16, alignItems: 'center' }}>
        <input
          placeholder="Proxy username"
          value={proxyUser}
          autoComplete="username"
          onChange={(e) => setProxyUser(e.target.value)}
          disabled={!proxyRequired || busy}
          required={proxyRequired}
        />
        <input
          placeholder="Proxy password"
          type="password"
          value={proxyPassword}
          autoComplete="current-password"
          onChange={(e) => setProxyPassword(e.target.value)}
          disabled={!proxyRequired || busy}
          required={proxyRequired}
        />
        <button className="btn" disabled={!proxyRequired || busy}>
          {busy ? 'Fetching…' : 'Fetch GitHub releases'}
        </button>
      </form>
      {proxyRequired && (
        <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
          Direct GitHub failed. Enter IITD kerberos id/password — LabWatch logs into proxy.cgi on this host (not stored), then fetches releases.
        </p>
      )}

      {(busy && proxyRequired) || fetchProgress != null ? (
        <ProgressPanel
          job={{
            active: busy && proxyRequired,
            label: 'Fetching GitHub releases',
            message: busy ? 'Campus proxy login + GitHub API…' : 'Done',
            progress: fetchProgress,
            state: busy ? 'running' : 'ok',
          }}
        />
      ) : null}

      {err && <p className="err">{err}</p>}

      {applyStuck && (
        <p className="err">
          Apply looks stuck. Use Cancel / Reset, then run Update again — or wait a moment for auto-reset.
        </p>
      )}

      {st && st.state !== 'idle' && (
        <ProgressPanel
          showWhenIdle
          job={{
            active: applyActive && !applyStuck,
            label: st.tag ? `Apply ${st.tag}` : 'Server apply',
            message: st.message,
            progress: st.progress,
            step: st.step,
            state: progressError ? 'error' : st.state,
            log: st.log || st.log_tail || '',
            error: progressError,
          }}
        />
      )}

      {!loading && !shown && !err && (
        <p className="muted">No releases yet. If you are on campus proxy, enter credentials and fetch.</p>
      )}

      {shown && (
        <>
          <div className="grid stats" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', marginBottom: 16 }}>
            <div className="card stat"><div className="label">Current</div><div className="value">{shown.current.tag}</div></div>
            <div className="card stat online"><div className="label">Latest</div><div className="value">{shown.latest?.tag || '—'}</div></div>
            <div className="card stat"><div className="label">Fetched</div><div className="value" style={{ fontSize: 18 }}>{shown.source}{shown.used_proxy ? ' (proxy)' : ''}</div></div>
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

          <div className="card toolbar" style={{ marginTop: 16, alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <span className="muted">Selected {selected || '—'}</span>
            <button
              className="btn"
              disabled={!chosen || busy || applyBlocked}
              onClick={() => void apply(applyStuck || st?.state === 'error' || st?.state === 'cancelled')}
            >
              {busy ? 'Working…' : applyActive && !applyStuck ? 'Applying…' : `${actionLabel} to ${selected || 'build'}`}
            </button>
            {canCancel && (
              <button className="btn secondary" disabled={busy} onClick={() => void cancelApply()}>
                Cancel / Reset
              </button>
            )}
            {(st?.state === 'error' || st?.state === 'cancelled' || st?.state === 'ok') && !applyActive && (
              <button className="btn secondary" disabled={busy} onClick={() => void cancelApply()}>
                Clear status
              </button>
            )}
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
