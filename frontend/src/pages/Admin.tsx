import type { FormEvent } from 'react'
import { useEffect, useState } from 'react'
import { ago, api } from '../api'
import { currentUser } from '../api'
import Infra from './Infra'
import Updates from './Updates'

type AdminTab = 'users' | 'labs' | 'updates' | 'tokens' | 'agents' | 'rules' | 'audit'

export default function Admin() {
  const role = currentUser()?.role
  if (role !== 'ADMIN') return <p className="err">Administrator role required.</p>
  const [tab, setTab] = useState<AdminTab>('users')
  return (
    <>
      <div className="topbar"><div><h2>Admin</h2><p>Users, labs, server updates, enrollment, thresholds</p></div></div>
      <div className="tabs">
        {(['users', 'labs', 'updates', 'tokens', 'agents', 'rules', 'audit'] as const).map((t) => (
          <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {tab === 'users' && <Users />}
      {tab === 'labs' && <Infra />}
      {tab === 'updates' && <Updates />}
      {tab === 'tokens' && <Tokens />}
      {tab === 'agents' && <Agents />}
      {tab === 'rules' && <Rules />}
      {tab === 'audit' && <Audit />}
    </>
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
      {created && <div className="card"><p>Store this token now; it will not be shown again.</p><code>{created}</code></div>}
      <div className="card" style={{ padding: 0 }}>
        <table>
          <thead><tr><th>Label</th><th>Prefix</th><th>Uses</th><th>Revoked</th><th></th></tr></thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id}>
                <td>{t.label}</td>
                <td className="mono">{t.prefix}</td>
                <td>{t.use_count}{t.max_uses ? ` / ${t.max_uses}` : ''}</td>
                <td>{t.revoked ? 'yes' : 'no'}</td>
                <td>{!t.revoked && <button className="btn danger" onClick={async () => { await api(`/api/admin/tokens/${t.id}/revoke`, { method: 'POST' }); load() }}>Revoke</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function Agents() {
  const [rows, setRows] = useState<any[]>([])
  const [secret, setSecret] = useState('')
  function load() { api('/api/admin/agents').then(setRows) }
  useEffect(load, [])
  return (
    <>
      {secret && <div className="card"><p>New agent secret (shown once)</p><code>{secret}</code></div>}
      <div className="card" style={{ padding: 0 }}>
        <table>
          <thead><tr><th>Host</th><th>Agent ID</th><th>Status</th><th>Seen</th><th></th></tr></thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id}>
                <td>{a.hostname}</td>
                <td className="mono">{a.agent_id}</td>
                <td>{a.status} {a.approved ? '' : '(pending)'}</td>
                <td>{ago(a.last_heartbeat_at)}</td>
                <td className="row-actions">
                  <button className="btn secondary" onClick={async () => { await api(`/api/admin/agents/${a.id}/approve`, { method: 'POST' }); load() }}>Approve</button>
                  <button className="btn secondary" onClick={async () => { const r = await api(`/api/admin/agents/${a.id}/rotate`, { method: 'POST' }); setSecret(r.agent_secret) }}>Rotate</button>
                  <button className="btn danger" onClick={async () => { await api(`/api/admin/agents/${a.id}/revoke`, { method: 'POST' }); load() }}>Revoke</button>
                </td>
              </tr>
            ))}
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
