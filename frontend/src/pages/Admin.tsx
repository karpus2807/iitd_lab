import type { FormEvent } from 'react'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ago, api } from '../api'
import { currentUser } from '../api'
import ProgressPanel from '../components/ProgressPanel'
import Infra from './Infra'
import Updates from './Updates'

const ADMIN_TABS = ['users', 'labs', 'updates', 'mail', 'tokens', 'agents', 'rules', 'audit'] as const
type AdminTab = (typeof ADMIN_TABS)[number]

export default function Admin() {
  const role = currentUser()?.role
  const [params, setParams] = useSearchParams()
  if (role !== 'ADMIN') return <p className="err">Administrator role required.</p>
  const raw = params.get('tab') || 'users'
  const tab: AdminTab = (ADMIN_TABS as readonly string[]).includes(raw) ? (raw as AdminTab) : 'users'
  return (
    <>
      <div className="topbar"><div><h2>Admin</h2><p>Users, labs, server updates, SMTP mail, enrollment, thresholds</p></div></div>
      <div className="tabs">
        {ADMIN_TABS.map((t) => (
          <button key={t} className={tab === t ? 'active' : ''} onClick={() => setParams({ tab: t })}>{t}</button>
        ))}
      </div>
      {tab === 'users' && <Users />}
      {tab === 'labs' && <Infra />}
      {tab === 'updates' && <Updates />}
      {tab === 'mail' && <MailSmtp />}
      {tab === 'tokens' && <Tokens />}
      {tab === 'agents' && <Agents />}
      {tab === 'rules' && <Rules />}
      {tab === 'audit' && <Audit />}
    </>
  )
}

function MailSmtp() {
  const [form, setForm] = useState({
    enabled: false,
    host: '',
    port: 25,
    username: '',
    password: '',
    from_addr: '',
    starttls: true,
    use_ssl: false,
    validate_certs: true,
    password_set: false,
  })
  const [testTo, setTestTo] = useState('')
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    const data = await api<any>('/api/admin/smtp')
    setForm({
      enabled: !!data.enabled,
      host: data.host || '',
      port: Number(data.port || 25),
      username: data.username || '',
      password: '',
      from_addr: data.from_addr || '',
      starttls: data.starttls !== false,
      use_ssl: !!data.use_ssl,
      validate_certs: data.validate_certs !== false,
      password_set: !!data.password_set,
    })
  }
  useEffect(() => {
    load().catch((e) => setErr(e.message))
  }, [])

  function applyIitdPreset(mode: 'starttls25' | 'ssl465') {
    if (mode === 'ssl465') {
      setForm((f) => ({
        ...f,
        host: f.host || 'smtp.iitd.ac.in',
        port: 465,
        starttls: false,
        use_ssl: true,
      }))
    } else {
      setForm((f) => ({
        ...f,
        host: f.host || 'smtp.iitd.ac.in',
        port: 25,
        starttls: true,
        use_ssl: false,
      }))
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr('')
    setMsg('')
    try {
      const body: any = {
        enabled: form.enabled,
        host: form.host.trim(),
        port: Number(form.port) || 25,
        username: form.username.trim(),
        from_addr: form.from_addr.trim(),
        starttls: form.starttls,
        use_ssl: form.use_ssl,
        validate_certs: form.validate_certs,
      }
      if (form.password.trim()) body.password = form.password
      const data = await api<any>('/api/admin/smtp', { method: 'PUT', body: JSON.stringify(body) })
      setForm((f) => ({
        ...f,
        password: '',
        password_set: !!data.password_set,
        enabled: !!data.enabled,
        starttls: data.starttls !== false,
        use_ssl: !!data.use_ssl,
        validate_certs: data.validate_certs !== false,
        port: Number(data.port || f.port),
      }))
      setMsg('SMTP settings saved')
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function sendTest() {
    setBusy(true)
    setErr('')
    setMsg('')
    try {
      await api('/api/admin/smtp/test', { method: 'POST', body: JSON.stringify({ to: testTo.trim() }) })
      setMsg(`Test email sent to ${testTo.trim()}`)
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>SMTP mail server</h3>
      <p className="muted">
        IITD CSC: <span className="mono">smtp.iitd.ac.in</span> — STARTTLS on port <strong>25</strong>, or SSL/TLS on{' '}
        <strong>465</strong>. Username = Kerberos login id (not full email). Auth required for outbound.
      </p>
      <div className="toolbar" style={{ gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <button className="btn secondary" type="button" onClick={() => applyIitdPreset('starttls25')}>
          IITD preset: 25 + STARTTLS
        </button>
        <button className="btn secondary" type="button" onClick={() => applyIitdPreset('ssl465')}>
          IITD preset: 465 + SSL
        </button>
      </div>
      {err && <p className="err">{err}</p>}
      {msg && <p className="muted">{msg}</p>}
      <form onSubmit={save} className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
          Enable SMTP
        </label>
        <label>
          Host
          <input required={form.enabled} value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} placeholder="smtp.iitd.ac.in" />
        </label>
        <label>
          Port
          <input type="number" value={form.port} onChange={(e) => setForm({ ...form, port: Number(e.target.value) })} />
        </label>
        <label>
          Username (Kerberos id)
          <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="yourloginid" />
        </label>
        <label>
          Password {form.password_set ? <span className="muted">(saved — leave blank to keep)</span> : null}
          <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder={form.password_set ? '••••••••' : ''} autoComplete="new-password" />
        </label>
        <label>
          From address
          <input value={form.from_addr} onChange={(e) => setForm({ ...form, from_addr: e.target.value })} placeholder="you@cse.iitd.ac.in" />
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="checkbox"
            checked={form.starttls && !form.use_ssl}
            onChange={(e) => setForm({ ...form, starttls: e.target.checked, use_ssl: e.target.checked ? false : form.use_ssl })}
          />
          STARTTLS (port 25)
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="checkbox"
            checked={form.use_ssl || form.port === 465}
            onChange={(e) =>
              setForm({
                ...form,
                use_ssl: e.target.checked,
                starttls: e.target.checked ? false : form.starttls,
                port: e.target.checked ? 465 : form.port === 465 ? 25 : form.port,
              })
            }
          />
          SSL/TLS (port 465)
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input type="checkbox" checked={form.validate_certs} onChange={(e) => setForm({ ...form, validate_certs: e.target.checked })} />
          Verify TLS certificates
        </label>
        <div className="toolbar" style={{ gridColumn: '1 / -1', gap: 8 }}>
          <button className="btn" disabled={busy} type="submit">{busy ? 'Saving…' : 'Save SMTP'}</button>
        </div>
      </form>
      <div className="toolbar" style={{ marginTop: 16, gap: 8, flexWrap: 'wrap' }}>
        <input
          placeholder="Test recipient email"
          value={testTo}
          onChange={(e) => setTestTo(e.target.value)}
          style={{ minWidth: 240 }}
        />
        <button className="btn secondary" type="button" disabled={busy || !testTo.trim()} onClick={() => void sendTest()}>
          Send test email
        </button>
      </div>
    </div>
  )
}

function Users() {
  const me = currentUser()
  const [rows, setRows] = useState<any[]>([])
  const [drafts, setDrafts] = useState<Record<string, any>>({})
  const [form, setForm] = useState({ username: '', email: '', password: '', role: 'VIEWER', full_name: '' })
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  async function load() {
    const list = await api<any[]>('/api/admin/users')
    setRows(list)
    const next: Record<string, any> = {}
    list.forEach((u) => {
      next[u.id] = { username: u.username, email: u.email, full_name: u.full_name || '', role: u.role, password: '' }
    })
    setDrafts(next)
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])

  async function create(e: FormEvent) {
    e.preventDefault()
    setErr('')
    try {
      await api('/api/admin/users', { method: 'POST', body: JSON.stringify(form) })
      setForm({ username: '', email: '', password: '', role: 'VIEWER', full_name: '' })
      setMsg('User created')
      await load()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function save(id: string) {
    const d = drafts[id] || {}
    setErr('')
    const body: any = { username: d.username, email: d.email, full_name: d.full_name, role: d.role }
    if (d.password) body.password = d.password
    try {
      await api(`/api/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
      setMsg(d.password ? 'User saved (password updated)' : 'User saved')
      await load()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function toggle(u: any) {
    setErr('')
    try {
      await api(`/api/admin/users/${u.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !u.is_active }) })
      await load()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function remove(u: any) {
    if (!confirm(`Delete user ${u.username}? This cannot be undone.`)) return
    setErr('')
    try {
      await api(`/api/admin/users/${u.id}`, { method: 'DELETE' })
      setMsg(`Deleted ${u.username}`)
      await load()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  return (
    <>
      {err && <p className="err">{err}</p>}
      {msg && <p className="muted">{msg}</p>}
      <form className="card toolbar" onSubmit={create}>
        <input placeholder="username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required />
        <input placeholder="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
        <input placeholder="full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
        <input placeholder="password" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required minLength={8} />
        <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
          <option>ADMIN</option><option>OPERATOR</option><option>VIEWER</option>
        </select>
        <button className="btn">Create user</button>
      </form>
      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        <table>
          <thead>
            <tr><th>Username</th><th>Email</th><th>Name</th><th>Role</th><th>New password</th><th>Active</th><th></th></tr>
          </thead>
          <tbody>
            {rows.map((u) => {
              const d = drafts[u.id] || {}
              const mine = me?.user_id === u.id
              return (
                <tr key={u.id}>
                  <td><input value={d.username ?? u.username} onChange={(e) => setDrafts({ ...drafts, [u.id]: { ...d, username: e.target.value } })} /></td>
                  <td><input value={d.email ?? u.email} onChange={(e) => setDrafts({ ...drafts, [u.id]: { ...d, email: e.target.value } })} /></td>
                  <td><input value={d.full_name ?? ''} onChange={(e) => setDrafts({ ...drafts, [u.id]: { ...d, full_name: e.target.value } })} /></td>
                  <td>
                    <select value={d.role ?? u.role} onChange={(e) => setDrafts({ ...drafts, [u.id]: { ...d, role: e.target.value } })}>
                      <option>ADMIN</option><option>OPERATOR</option><option>VIEWER</option>
                    </select>
                  </td>
                  <td><input type="password" placeholder="leave blank" value={d.password ?? ''} onChange={(e) => setDrafts({ ...drafts, [u.id]: { ...d, password: e.target.value } })} minLength={8} /></td>
                  <td>{u.is_active ? 'yes' : 'no'}</td>
                  <td className="row-actions">
                    <button className="btn secondary" type="button" onClick={() => save(u.id)}>Save</button>
                    <button className="btn secondary" type="button" onClick={() => toggle(u)}>{u.is_active ? 'Disable' : 'Enable'}</button>
                    <button className="btn danger" type="button" disabled={mine} onClick={() => remove(u)}>Delete</button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function tokenStatusLabel(status: string) {
  switch (status) {
    case 'used':
      return 'Used'
    case 'unused':
      return 'Unused'
    case 'revoked':
      return 'Revoked'
    case 'expired':
      return 'Expired'
    case 'exhausted':
      return 'Exhausted'
    default:
      return status || '—'
  }
}

function Tokens() {
  const [rows, setRows] = useState<any[]>([])
  const [labs, setLabs] = useState<any[]>([])
  const [created, setCreated] = useState('')
  const [label, setLabel] = useState('lab-enrollment')
  const [labId, setLabId] = useState('')
  function load() { api('/api/admin/tokens').then(setRows) }
  useEffect(() => { load(); api('/api/labs').then(setLabs) }, [])
  async function create(e: FormEvent) {
    e.preventDefault()
    const body: any = { label, expires_hours: 168 }
    if (labId) body.lab_id = labId
    const r = await api('/api/admin/tokens', { method: 'POST', body: JSON.stringify(body) })
    setCreated(r.token)
    load()
  }
  const autoDays = rows[0]?.unused_auto_delete_days ?? 2
  return (
    <>
      <form className="card toolbar" onSubmit={create}>
        <input value={label} onChange={(e) => setLabel(e.target.value)} />
        <select value={labId} onChange={(e) => setLabId(e.target.value)}>
          <option value="">Any lab</option>
          {labs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
        <button className="btn">New registration token</button>
      </form>
      <p className="muted" style={{ margin: '0 0 12px', fontSize: 13 }}>
        Status shows whether a token enrolled any agent. Unused tokens (0 uses) are auto-revoked and deleted after {autoDays} day{autoDays === 1 ? '' : 's'}
        (and immediately if already past expiry). Opening this page also runs cleanup.
      </p>
      {created && <div className="card"><p>Store this token now; it will not be shown again.</p><code>{created}</code></div>}
      <div className="card" style={{ padding: 0 }}>
        <table>
          <thead>
            <tr>
              <th>Label</th>
              <th>Prefix</th>
              <th>Status</th>
              <th>Uses</th>
              <th>Last used</th>
              <th>Created</th>
              <th>Auto-remove</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => {
              const st = t.status || (t.revoked ? 'revoked' : t.use_count > 0 ? 'used' : 'unused')
              return (
                <tr key={t.id}>
                  <td>{t.label}</td>
                  <td className="mono">{t.prefix}</td>
                  <td>
                    <strong className={st === 'unused' ? 'err' : st === 'used' ? '' : 'muted'}>
                      {tokenStatusLabel(st)}
                    </strong>
                    {typeof t.enrolled_agents === 'number' && t.enrolled_agents > 0 ? (
                      <div className="muted" style={{ fontSize: 12 }}>{t.enrolled_agents} agent(s) enrolled</div>
                    ) : null}
                  </td>
                  <td>{t.use_count}{t.max_uses ? ` / ${t.max_uses}` : ''}</td>
                  <td>{t.last_used_at ? ago(t.last_used_at) : <span className="muted">never</span>}</td>
                  <td>{ago(t.created_at)}</td>
                  <td className="muted" style={{ fontSize: 12 }}>
                    {st === 'unused'
                      ? (t.unused_deletes_in_hours != null
                        ? `in ~${t.unused_deletes_in_hours}h`
                        : `after ${autoDays}d`)
                      : '—'}
                  </td>
                  <td>
                    {!t.revoked && st !== 'expired' && (
                      <button className="btn danger" onClick={async () => { await api(`/api/admin/tokens/${t.id}/revoke`, { method: 'POST' }); load() }}>Revoke</button>
                    )}
                  </td>
                </tr>
              )
            })}
            {!rows.length && (
              <tr><td colSpan={8} className="muted" style={{ padding: 16 }}>No registration tokens.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}

function Agents() {
  const [rows, setRows] = useState<any[]>([])
  const [agentPackVersion, setAgentPackVersion] = useState('')
  const [serverVersion, setServerVersion] = useState('')
  const [secret, setSecret] = useState('')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [trackIds, setTrackIds] = useState<string[]>([])
  const [sessionLog, setSessionLog] = useState('')

  function load() {
    return api('/api/admin/agents').then((data) => {
      const list = Array.isArray(data) ? data : (data.agents || [])
      if (!Array.isArray(data)) {
        setAgentPackVersion(data.agent_pack_version || data.current_version || '')
        setServerVersion(data.server_version || '')
      } else {
        setAgentPackVersion('')
        setServerVersion('')
      }
      setRows(list)
      setSelected((prev) => {
        const next: Record<string, boolean> = {}
        for (const a of list) {
          if (prev[a.id]) next[a.id] = true
        }
        return next
      })
      return list as any[]
    })
  }
  useEffect(() => {
    void load()
  }, [])

  const filtered = rows.filter((a) => {
    const needle = q.trim().toLowerCase()
    if (!needle) return true
    const hay = [a.hostname, a.inventory_id, a.agent_id, a.version, a.status]
      .map((x) => String(x || '').toLowerCase())
      .join(' ')
    return hay.includes(needle)
  })
  const selectedIds = filtered.filter((a) => selected[a.id]).map((a) => a.id)
  const allFilteredSelected = filtered.length > 0 && filtered.every((a) => selected[a.id])

  const trackSet = useMemo(() => new Set(trackIds), [trackIds])

  // Progress panel + per-row meters: ONLY agents queued in this browser action.
  const tracked = useMemo(() => {
    if (!trackIds.length) return []
    return rows.filter((a) => trackSet.has(a.id))
  }, [rows, trackIds, trackSet])

  const batchProgress = useMemo(() => {
    if (!trackIds.length || !tracked.length) return null
    const active = tracked.filter((a) => a.update_active)
    const failed = tracked.filter((a) => a.update_failed || (a.update_status || '').toLowerCase() === 'error')
    const ok = tracked.filter((a) => (a.update_status || '').toLowerCase() === 'ok')
    const pcts = tracked.map((a) => {
      if (typeof a.update_progress === 'number') return a.update_progress
      const st = (a.update_status || '').toLowerCase()
      if (st === 'ok') return 100
      if (st === 'error' || st === 'cancelled') return 0
      if (st === 'applying') return 85
      if (st === 'running' || st === 'downloading') return 55
      if (st === 'sent') return 35
      if (st === 'queued') return 12
      return 0
    })
    const progress = Math.round(pcts.reduce((s, n) => s + n, 0) / pcts.length)
    const lines = tracked.map((a) => {
      const st = a.update_status || '—'
      const pct = typeof a.update_progress === 'number' ? `${a.update_progress}%` : ''
      const msg = a.update_message ? ` — ${a.update_message}` : ''
      return `${a.hostname || a.agent_id}: ${st}${pct ? ` ${pct}` : ''}${msg}`
    })
    const stillActive = active.length > 0
    const state = failed.length && !stillActive ? 'error' : stillActive ? 'running' : ok.length ? 'ok' : 'idle'
    const one = tracked.length === 1 ? tracked[0] : null
    return {
      active: stillActive,
      progress,
      state,
      failed: failed.length,
      ok: ok.length,
      total: tracked.length,
      label: one
        ? `Update ${one.hostname || one.agent_id}${agentPackVersion ? ` → ${agentPackVersion}` : ''}`
        : `Update ${tracked.length} agents${agentPackVersion ? ` → ${agentPackVersion}` : ''}`,
      message: stillActive
        ? one
          ? `Updating ${one.hostname || one.agent_id}…`
          : `Updating ${active.length}/${tracked.length}…`
        : failed.length
          ? `${failed.length} failed · ${ok.length} ok`
          : ok.length === tracked.length
            ? one
              ? `${one.hostname || one.agent_id} updated`
              : `All ${ok.length} updated`
            : '',
      log: [...(sessionLog ? [sessionLog] : []), ...lines].join('\n'),
      errors: failed.map((a) => `${a.hostname}: ${a.update_message || a.update_status || 'error'}`),
    }
  }, [tracked, agentPackVersion, sessionLog, trackIds.length])

  const pollUpdates = Boolean(batchProgress?.active)

  useEffect(() => {
    if (!pollUpdates) return
    const id = window.setInterval(() => {
      void load()
    }, 2500)
    return () => window.clearInterval(id)
  }, [pollUpdates])

  // After success/error settles, drop tracking so leftover "ok" statuses don't keep meters around.
  useEffect(() => {
    if (!batchProgress || batchProgress.active) return
    if (!batchProgress.ok && !batchProgress.failed) return
    const t = window.setTimeout(() => {
      setTrackIds([])
      setSessionLog('')
    }, 8000)
    return () => window.clearTimeout(t)
  }, [batchProgress?.active, batchProgress?.ok, batchProgress?.failed, batchProgress?.state])

  function toggleAll(checked: boolean) {
    setSelected((prev) => {
      const next = { ...prev }
      for (const a of filtered) {
        if (checked) next[a.id] = true
        else delete next[a.id]
      }
      return next
    })
  }

  async function queueUpdate(ids: string[], opts?: { confirmMulti?: boolean }) {
    const unique = Array.from(new Set(ids.filter(Boolean)))
    if (!unique.length) {
      setNotice('Select at least one agent first.')
      return
    }
    if (opts?.confirmMulti && unique.length > 1) {
      if (!confirm(`Queue update to latest pack for ${unique.length} selected agents only?\n\nOther agents will not be updated.`)) {
        return
      }
    }
    setBusy(true)
    setNotice('')
    try {
      // Always send explicit IDs — never imply "all agents".
      const r = await api('/api/admin/agents/update', {
        method: 'POST',
        body: JSON.stringify({ agent_ids: unique }),
      })
      const queued = (r.queued || []) as string[]
      const n = queued.length
      const skipped = r.skipped || []
      setTrackIds(queued)
      setSessionLog(
        [
          `Queued ${n} agent${n === 1 ? '' : 's'} → ${r.target_version} (latest pack, one jump)`,
          `IDs: ${queued.join(', ')}`,
          skipped.length ? `Skipped: ${skipped.map((s: any) => `${s.id} (${s.reason})`).join(', ')}` : '',
        ]
          .filter(Boolean)
          .join('\n'),
      )
      setNotice(
        n === 1
          ? `Queued update to ${r.target_version} for 1 agent only. Others untouched.`
          : `Queued update to ${r.target_version} for ${n} selected agents only. Others untouched.`,
      )
      await load()
    } catch (e: any) {
      setNotice(e?.message || 'Update queue failed')
      setSessionLog(`ERROR: ${e?.message || 'Update queue failed'}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {secret && <div className="card"><p>New agent secret (shown once)</p><code>{secret}</code></div>}
      <div className="card" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
        <input
          style={{ flex: '1 1 220px', minWidth: 180 }}
          placeholder="Search host or Inv.ID…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button
          className="btn"
          disabled={busy || selectedIds.length === 0}
          onClick={() => void queueUpdate(selectedIds, { confirmMulti: true })}
          title={selectedIds.length ? `Update ${selectedIds.length} selected only` : 'Select agents with checkboxes first'}
        >
          Update selected{selectedIds.length ? ` (${selectedIds.length})` : ''}
        </button>
        <span className="muted" style={{ fontSize: 13 }}>
          Agent pack {agentPackVersion || '…'}
          {serverVersion ? ` · server app ${serverVersion}` : ''}
          {' · '}row “Update agent” = that host only · needs agent ≥1.1.40
        </span>
      </div>
      {notice && (
        <p className={notice.toLowerCase().includes('fail') ? 'err' : 'muted'} style={{ marginBottom: 8 }}>
          {notice}
        </p>
      )}
      {batchProgress && (batchProgress.active || batchProgress.failed > 0 || batchProgress.ok > 0) ? (
        <div style={{ marginBottom: 12 }}>
          <ProgressPanel
            showWhenIdle
            job={{
              active: batchProgress.active,
              label: batchProgress.label,
              message: batchProgress.message,
              progress: batchProgress.progress,
              step: batchProgress.active
                ? `${batchProgress.ok + batchProgress.failed}/${batchProgress.total} finished`
                : batchProgress.state,
              state: batchProgress.state,
              log: batchProgress.log,
              error: batchProgress.state === 'error' || batchProgress.failed > 0,
            }}
          />
          <button
            type="button"
            className="btn secondary"
            style={{ marginTop: 8 }}
            onClick={() => {
              setTrackIds([])
              setSessionLog('')
              setNotice('')
            }}
          >
            Dismiss progress
          </button>
        </div>
      ) : null}
      {batchProgress?.errors?.length ? (
        <div className="card" style={{ marginBottom: 12, borderColor: 'var(--danger, #c44)' }}>
          <strong>Update errors (this queue only)</strong>
          <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
            {batchProgress.errors.map((line) => (
              <li key={line} className="err" style={{ marginBottom: 4 }}>
                {line}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="card" style={{ padding: 0 }}>
        <table>
          <thead>
            <tr>
              <th style={{ width: 36 }}>
                <input
                  type="checkbox"
                  checked={allFilteredSelected}
                  onChange={(e) => toggleAll(e.target.checked)}
                  title="Select all"
                  aria-label="Select all"
                />
              </th>
              <th>Host</th>
              <th>Inv.ID</th>
              <th>Agent ID</th>
              <th>Ver</th>
              <th>Status</th>
              <th>
                Update
                {agentPackVersion ? (
                  <div className="muted" style={{ fontWeight: 400, fontSize: 12 }}>pack {agentPackVersion}</div>
                ) : null}
              </th>
              <th>Seen</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((a) => {
              const inThisQueue = trackSet.has(a.id)
              const st = inThisQueue ? (a.update_status || '').toLowerCase() : ''
              const pct = inThisQueue && typeof a.update_progress === 'number' ? a.update_progress : null
              const failed = inThisQueue && (a.update_failed || st === 'error')
              const active = inThisQueue && a.update_active
              return (
                <tr key={a.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={!!selected[a.id]}
                      onChange={(e) => setSelected((prev) => {
                        const next = { ...prev }
                        if (e.target.checked) next[a.id] = true
                        else delete next[a.id]
                        return next
                      })}
                      aria-label={`Select ${a.hostname}`}
                    />
                  </td>
                  <td>{a.hostname}</td>
                  <td className="mono">{a.inventory_id || '—'}</td>
                  <td className="mono">{a.agent_id}</td>
                  <td>
                    <span
                      className="mono agent-ver-pill"
                      data-state={a.update_available ? 'behind' : a.up_to_date ? 'current' : 'unknown'}
                      title={
                        a.update_available
                          ? `Update available → agent pack ${agentPackVersion || a.agent_pack_version || a.current_version || '?'}`
                          : a.up_to_date
                            ? `Up to date (${a.version})`
                            : 'Version unknown'
                      }
                    >
                      {a.version || '—'}
                    </span>
                  </td>
                  <td>{a.status} {a.approved ? '' : '(pending)'}</td>
                  <td
                    className="agent-update-cell"
                    data-state={failed ? 'behind' : a.update_available ? 'behind' : a.up_to_date ? 'current' : 'unknown'}
                    style={{ fontSize: 12, minWidth: 140 }}
                  >
                    {a.update_available ? (
                      <strong>update available</strong>
                    ) : a.up_to_date ? (
                      <strong>up to date</strong>
                    ) : (
                      <span className="muted">—</span>
                    )}
                    {inThisQueue && st ? (
                      <div className={failed ? 'err' : 'muted'} style={{ marginTop: 4 }}>
                        <strong>{st}</strong>
                        {pct != null ? ` · ${pct}%` : ''}
                        {a.update_target_version ? ` → ${a.update_target_version}` : ''}
                        {a.update_message ? (
                          <div style={{ marginTop: 2 }}>{a.update_message}</div>
                        ) : null}
                        {(active || failed || st === 'ok') && pct != null ? (
                          <div className={`meter${failed ? ' crit' : ''}`} style={{ marginTop: 6 }}>
                            <i style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    {!a.remote_update_capable && a.version ? (
                      <div className="muted" title="Needs one manual install of ≥1.1.40">manual first</div>
                    ) : null}
                  </td>
                  <td>{ago(a.last_heartbeat_at)}</td>
                  <td className="row-actions">
                    <button
                      className="btn secondary"
                      disabled={busy || active}
                      title={active ? 'Update already in progress for this agent' : `Update only ${a.hostname || a.agent_id} to pack ${agentPackVersion || 'latest'}`}
                      onClick={() => void queueUpdate([a.id])}
                    >
                      Update agent
                    </button>
                    <button className="btn secondary" onClick={async () => { await api(`/api/admin/agents/${a.id}/approve`, { method: 'POST' }); load() }}>Approve</button>
                    <button className="btn secondary" onClick={async () => { const r = await api(`/api/admin/agents/${a.id}/rotate`, { method: 'POST' }); setSecret(r.agent_secret) }}>Rotate</button>
                    <button className="btn danger" onClick={async () => { await api(`/api/admin/agents/${a.id}/revoke`, { method: 'POST' }); load() }}>Revoke</button>
                    <button className="btn danger" onClick={async () => {
                      if (!confirm(`Remove ${a.hostname} from LabWatch? This deletes the host on the server.`)) return
                      await api(`/api/machines/${a.machine_id}`, { method: 'DELETE' })
                      load()
                    }}>Remove host</button>
                  </td>
                </tr>
              )
            })}
            {!filtered.length && (
              <tr><td colSpan={9} className="muted" style={{ padding: 16 }}>No agents match.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}

function Rules() {
  const [rows, setRows] = useState<any[]>([])
  function load() { api('/api/alerts/rules').then(setRows) }
  useEffect(load, [])
  async function save(r: any) {
    await api(`/api/alerts/rules/${r.id}`, { method: 'PUT', body: JSON.stringify(r) })
    load()
  }
  return (
    <div className="card" style={{ padding: 0 }}>
      <table>
        <thead><tr><th>Rule</th><th>Severity</th><th>Enabled</th><th>Threshold</th><th></th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id}>
              <td>{r.name}<div className="muted">{r.description}</div></td>
              <td>
                <select value={r.severity} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, severity: e.target.value } : x))}>
                  <option>INFO</option><option>WARNING</option><option>CRITICAL</option>
                </select>
              </td>
              <td><input type="checkbox" checked={r.enabled} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, enabled: e.target.checked } : x))} /></td>
              <td>
                {r.rule_type === 'METRIC' ? (
                  <input type="number" value={r.threshold ?? ''} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, threshold: Number(e.target.value) } : x))} />
                ) : r.event_type}
              </td>
              <td><button className="btn secondary" onClick={() => save(r)}>Save</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Audit() {
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => { api('/api/audit').then(setRows) }, [])
  return (
    <div className="card" style={{ padding: 0 }}>
      <table>
        <thead><tr><th>When</th><th>User</th><th>Action</th><th>Details</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{ago(r.created_at)}</td>
              <td>{r.username}</td>
              <td className="mono">{r.action}</td>
              <td className="muted">{JSON.stringify(r.details)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
