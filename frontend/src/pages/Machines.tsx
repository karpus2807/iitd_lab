import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ago, api, currentUser } from '../api'
import { StatusBadge } from '../Layout'

export default function Machines() {
  const [rows, setRows] = useState<any[]>([])
  const [labs, setLabs] = useState<any[]>([])
  const [err, setErr] = useState('')
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const role = currentUser()?.role
  const canAssign = role === 'ADMIN' || role === 'OPERATOR'
  const q = params.get('q') || ''
  const lab = params.get('lab') || ''
  const status = params.get('status') || ''
  const os = params.get('os') || ''
  const alerts = params.get('alerts') || ''
  const gpu = params.get('gpu') || ''

  useEffect(() => {
    api('/api/labs').then(setLabs).catch(() => undefined)
  }, [])

  const loadRows = useCallback(() => {
    const qs = new URLSearchParams()
    if (q) qs.set('q', q)
    if (lab) qs.set('lab_id', lab)
    if (status) qs.set('status', status)
    if (os) qs.set('os_name', os)
    if (alerts === '1') qs.set('has_alerts', 'true')
    if (gpu === '1') qs.set('has_gpu', 'true')
    api(`/api/machines?${qs}`).then(setRows).catch(() => setRows([]))
  }, [q, lab, status, os, alerts, gpu])

  useEffect(() => {
    loadRows()
  }, [loadRows])

  const osOptions = useMemo(() => Array.from(new Set(rows.map((r) => r.os_name).filter(Boolean))), [rows])

  function set(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next)
  }

  async function assignLab(machineId: string, labId: string) {
    if (!labId) return
    setErr('')
    try {
      await api(`/api/machines/${machineId}`, { method: 'PATCH', body: JSON.stringify({ lab_id: labId }) })
      loadRows()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not assign lab')
    }
  }

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Machines</h2>
          <p>{rows.length} matching hosts{canAssign ? ' · change Lab in the list to move a host, including Unassigned' : ''}</p>
        </div>
      </div>
      {err && <p className="err">{err}</p>}
      <div className="toolbar">
        <input placeholder="Search machine ID, hostname or IP" value={q} onChange={(e) => set('q', e.target.value)} />
        <select value={lab} onChange={(e) => set('lab', e.target.value)}>
          <option value="">All labs</option>
          {labs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
        <select value={status} onChange={(e) => set('status', e.target.value)}>
          <option value="">All statuses</option>
          <option>ONLINE</option>
          <option>OFFLINE</option>
          <option>NEVER_CONNECTED</option>
          <option>AGENT_UNHEALTHY</option>
        </select>
        <select value={os} onChange={(e) => set('os', e.target.value)}>
          <option value="">All OS</option>
          {osOptions.map((o) => <option key={o}>{o}</option>)}
        </select>
        <select value={gpu} onChange={(e) => set('gpu', e.target.value)}>
          <option value="">GPU filter</option>
          <option value="1">Has GPU</option>
        </select>
        <select value={alerts} onChange={(e) => set('alerts', e.target.value)}>
          <option value="">Alerts</option>
          <option value="1">Open alerts</option>
        </select>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <table>
          <thead>
            <tr>
              <th>Machine ID</th><th>Lab</th><th>Status</th><th>OS</th><th>IP</th><th>GPUs</th><th>Seen</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.id} className="clickable" onClick={() => nav(`/machines/${m.id}`)}>
                <td>
                  <Link to={`/machines/${m.id}`}><strong>{m.inventory_id || m.display_name || m.hostname}</strong></Link>
                  {m.inventory_id && m.hostname ? <div className="muted">{m.hostname}</div> : null}
                  {m.has_open_alerts && <span className="badge WARNING" style={{ marginLeft: 8 }}>alert</span>}
                  {m.is_virtual && <span className="badge INFO" style={{ marginLeft: 8 }}>VM</span>}
                </td>
                <td onClick={(e) => e.stopPropagation()} onMouseDown={(e) => e.stopPropagation()}>
                  {canAssign ? (
                    <select
                      className="lab-assign"
                      value={m.lab_id || ''}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => assignLab(m.id, e.target.value)}
                    >
                      {!m.lab_id && <option value="">Pick a lab</option>}
                      {labs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                    </select>
                  ) : (m.lab_name || '—')}
                </td>
                <td><StatusBadge status={m.status} /></td>
                <td>{m.os_name} {m.architecture}</td>
                <td className="mono">{m.current_ip || '—'}{(m.current_ips || []).length > 1 ? ` +${m.current_ips.length - 1}` : ''}</td>
                <td className="mono">{m.gpu_count}</td>
                <td className="muted">{ago(m.last_seen_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
