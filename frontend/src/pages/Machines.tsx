import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ago, api, currentUser } from '../api'
import { StatusBadge } from '../Layout'
import PageBar, { PAGE_SIZE } from '../components/PageBar'

export default function Machines() {
  const [rows, setRows] = useState<any[]>([])
  const [labs, setLabs] = useState<any[]>([])
  const [err, setErr] = useState('')
  const [page, setPage] = useState(1)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editPet, setEditPet] = useState('')
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const role = currentUser()?.role
  const canManage = role === 'ADMIN' || role === 'OPERATOR'
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

  useEffect(() => {
    setPage(1)
  }, [q, lab, status, os, alerts, gpu])

  const osOptions = useMemo(() => Array.from(new Set(rows.map((r) => r.os_name).filter(Boolean))), [rows])
  const pageRows = useMemo(
    () => rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [rows, page],
  )

  function set(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next)
  }

  async function removeMachine(m: any) {
    const name = m.inventory_id || m.display_name || m.hostname
    if (!confirm(`Remove ${name} from LabWatch? This deletes the host on the server.`)) return
    setErr('')
    try {
      await api(`/api/machines/${m.id}`, { method: 'DELETE' })
      loadRows()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not remove machine')
    }
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

  function startEditPet(m: any, e: MouseEvent) {
    e.stopPropagation()
    setEditingId(m.id)
    setEditPet(m.pet_name || '')
  }

  async function savePet(machineId: string) {
    setErr('')
    try {
      await api(`/api/machines/${machineId}`, {
        method: 'PATCH',
        body: JSON.stringify({ pet_name: editPet.trim() }),
      })
      setEditingId(null)
      loadRows()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not save pet name')
    }
  }

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Machines</h2>
          <p>{rows.length} matching hosts{canManage ? ' · edit Pet name, change Lab, or Remove' : ''}</p>
        </div>
      </div>
      {err && <p className="err">{err}</p>}
      <div className="toolbar">
        <input placeholder="Search pet name, machine ID, hostname or IP" value={q} onChange={(e) => set('q', e.target.value)} />
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
              <th>Pet name</th><th>Machine ID</th><th>Lab</th><th>Status</th><th>OS</th><th>IP</th><th>GPUs</th><th>Seen</th>{canManage ? <th></th> : null}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((m) => (
              <tr key={m.id} className="clickable" onClick={() => nav(`/machines/${m.id}`)}>
                <td onClick={(e) => e.stopPropagation()} onMouseDown={(e) => e.stopPropagation()}>
                  {canManage && editingId === m.id ? (
                    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                      <input
                        autoFocus
                        value={editPet}
                        placeholder="optional"
                        onChange={(e) => setEditPet(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') void savePet(m.id)
                          if (e.key === 'Escape') setEditingId(null)
                        }}
                        style={{ minWidth: 120, maxWidth: 200 }}
                      />
                      <button className="btn" type="button" onClick={() => void savePet(m.id)}>Save</button>
                      <button className="btn" type="button" onClick={() => setEditingId(null)}>Cancel</button>
                    </span>
                  ) : (
                    <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                      <span>{m.pet_name || <span className="muted">—</span>}</span>
                      {canManage && (
                        <button className="btn" type="button" style={{ padding: '2px 8px', fontSize: 12 }} onClick={(e) => startEditPet(m, e)}>
                          Edit
                        </button>
                      )}
                    </span>
                  )}
                </td>
                <td>
                  <Link to={`/machines/${m.id}`}><strong>{m.inventory_id || m.display_name || m.hostname}</strong></Link>
                  {m.inventory_id && m.hostname ? <div className="muted">{m.hostname}</div> : null}
                  {m.has_open_alerts && <span className="badge WARNING" style={{ marginLeft: 8 }}>alert</span>}
                  {m.is_virtual && <span className="badge INFO" style={{ marginLeft: 8 }}>VM</span>}
                </td>
                <td onClick={(e) => e.stopPropagation()} onMouseDown={(e) => e.stopPropagation()}>
                  {canManage ? (
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
                {canManage && (
                  <td onClick={(e) => e.stopPropagation()} onMouseDown={(e) => e.stopPropagation()}>
                    <button className="btn danger" type="button" onClick={() => removeMachine(m)}>Remove</button>
                  </td>
                )}
              </tr>
            ))}
            {!pageRows.length && (
              <tr><td colSpan={canManage ? 9 : 8} className="muted" style={{ padding: 16 }}>No matching machines.</td></tr>
            )}
          </tbody>
        </table>
        <PageBar page={page} total={rows.length} onChange={setPage} />
      </div>
    </>
  )
}
