import { useEffect, useState } from 'react'
import { ago, api } from '../api'
import { currentUser } from '../api'

function pingAlerts() {
  window.dispatchEvent(new Event('lw-alerts-changed'))
}

export default function Alerts() {
  const [rows, setRows] = useState<any[]>([])
  const [status, setStatus] = useState('OPEN')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  const canAck = ['ADMIN', 'OPERATOR'].includes(currentUser()?.role || '')

  function load() {
    const qs = status ? `?status=${status}` : ''
    api(`/api/alerts${qs}`).then(setRows).catch((e) => setErr(e instanceof Error ? e.message : 'Could not load alerts'))
  }
  useEffect(load, [status])

  async function ack(id: string) {
    await api(`/api/alerts/${id}/acknowledge`, { method: 'POST' })
    pingAlerts()
    load()
  }
  async function resolve(id: string) {
    await api(`/api/alerts/${id}/resolve`, { method: 'POST' })
    pingAlerts()
    load()
  }
  async function removeOne(id: string) {
    if (!confirm('Delete this alert?')) return
    await api(`/api/alerts/${id}`, { method: 'DELETE' })
    pingAlerts()
    load()
  }
  async function clearKind(kind: 'resolved' | 'all') {
    const msg = kind === 'resolved' ? 'Clear all resolved alerts?' : 'Clear ALL alerts (open and resolved)?'
    if (!confirm(msg)) return
    setErr('')
    setBusy(kind)
    try {
      const path = kind === 'resolved' ? '/api/alerts?status=RESOLVED' : '/api/alerts'
      await api(path, { method: 'DELETE' })
      pingAlerts()
      load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not clear alerts')
    } finally {
      setBusy('')
    }
  }

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Alerts</h2>
          <p>Open alerts only count in the sidebar. Resolve or clear to drop the number.</p>
        </div>
        {canAck && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn secondary" type="button" disabled={busy === 'resolved'} onClick={() => clearKind('resolved')}>
              Clear resolved
            </button>
            <button className="btn danger" type="button" disabled={busy === 'all'} onClick={() => clearKind('all')}>
              Clear all
            </button>
          </div>
        )}
      </div>
      {err && <p className="err">{err}</p>}
      <div className="toolbar">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>
          <option>OPEN</option>
          <option>ACKNOWLEDGED</option>
          <option>RESOLVED</option>
        </select>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <table>
          <thead><tr><th>When</th><th>Host</th><th>Severity</th><th>Status</th><th>Alert</th><th></th></tr></thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id}>
                <td className="muted">{ago(a.created_at)}</td>
                <td>{a.hostname}</td>
                <td><span className={`badge ${a.severity}`}>{a.severity}</span></td>
                <td>{a.status}</td>
                <td>{a.title}<div className="muted">{a.message}</div></td>
                <td className="row-actions">
                  {canAck && a.status === 'OPEN' && <button className="btn secondary" onClick={() => ack(a.id)}>Ack</button>}
                  {canAck && a.status !== 'RESOLVED' && <button className="btn secondary" onClick={() => resolve(a.id)}>Resolve</button>}
                  {canAck && <button className="btn danger" type="button" onClick={() => removeOne(a.id)}>Delete</button>}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={6} className="muted" style={{ padding: 16 }}>No alerts in this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}
