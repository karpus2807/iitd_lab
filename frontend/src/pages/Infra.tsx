import type { FormEvent } from 'react'
import { useEffect, useState } from 'react'
import { api, currentUser } from '../api'

type Lab = {
  id: string
  name: string
  code: string
  building: string
  floor: string
  room: string
  capacity: number
  phone: string
  description: string
  machine_count: number
  online_count: number
  protected?: boolean
}

type Machine = {
  id: string
  hostname: string
  display_name: string
  inventory_id?: string | null
  lab_id?: string | null
  status: string
  approved: boolean
}

const EMPTY_LAB = {
  name: '', code: '', building: '', floor: '', room: '',
  capacity: 0, phone: '', description: '',
}

export default function Infra() {
  const role = currentUser()?.role
  const canEdit = role === 'ADMIN' || role === 'OPERATOR'
  const [labs, setLabs] = useState<Lab[]>([])
  const [machines, setMachines] = useState<Machine[]>([])
  const [drafts, setDrafts] = useState<Record<string, Partial<Lab>>>({})
  const [hostDrafts, setHostDrafts] = useState<Record<string, { display_name: string; lab_id: string; approved: boolean }>>({})
  const [form, setForm] = useState({ ...EMPTY_LAB })
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  async function load() {
    const [labRows, hostRows] = await Promise.all([api<Lab[]>('/api/labs'), api<Machine[]>('/api/machines')])
    setLabs(labRows)
    setMachines(hostRows)
    const next: Record<string, Partial<Lab>> = {}
    labRows.forEach((l) => {
      next[l.id] = {
        name: l.name, code: l.code || '', building: l.building || '',
        floor: l.floor || '', room: l.room || '', capacity: l.capacity || 0,
        phone: l.phone || '', description: l.description || '',
      }
    })
    setDrafts(next)
    const hosts: Record<string, { display_name: string; lab_id: string; approved: boolean }> = {}
    hostRows.forEach((m) => {
      hosts[m.id] = { display_name: m.display_name || '', lab_id: m.lab_id || '', approved: !!m.approved }
    })
    setHostDrafts(hosts)
  }

  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])

  function setDraft(id: string, patch: Partial<Lab>) {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }))
  }

  async function create(e: FormEvent) {
    e.preventDefault()
    setErr('')
    await api('/api/labs', { method: 'POST', body: JSON.stringify({ ...form, capacity: Number(form.capacity) || 0 }) })
    setForm({ ...EMPTY_LAB })
    setMsg('Lab created')
    await load()
  }

  async function saveLab(id: string) {
    setErr('')
    const body = { ...drafts[id], capacity: Number(drafts[id]?.capacity) || 0 }
    await api(`/api/labs/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
    setMsg('Lab saved')
    await load()
  }

  async function removeLab(lab: Lab) {
    if (!confirm(`Delete ${lab.name}? Machines move to Unassigned.`)) return
    setErr('')
    await api(`/api/labs/${lab.id}`, { method: 'DELETE' })
    setMsg('Lab deleted')
    await load()
  }

  async function saveMachine(id: string) {
    const d = hostDrafts[id]
    await api(`/api/machines/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ display_name: d.display_name, lab_id: d.lab_id || null, approved: d.approved }),
    })
    setMsg('Machine saved')
    await load()
  }

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Labs</h2>
          <p>Name, code, building, floor, room, capacity, phone, and notes. Delete moves hosts to Unassigned.</p>
        </div>
      </div>
      {err && <p className="err">{err}</p>}
      {msg && <p className="muted">{msg}</p>}
      {canEdit && (
        <form className="card" onSubmit={create} style={{ marginBottom: 16 }}>
          <h3 className="section-title">Add lab</h3>
          <div className="toolbar">
            <input placeholder="Lab name *" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            <input placeholder="Code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
            <input placeholder="Building" value={form.building} onChange={(e) => setForm({ ...form, building: e.target.value })} />
            <input placeholder="Floor" value={form.floor} onChange={(e) => setForm({ ...form, floor: e.target.value })} />
            <input placeholder="Room" value={form.room} onChange={(e) => setForm({ ...form, room: e.target.value })} />
            <input placeholder="Capacity" type="number" min={0} value={form.capacity} onChange={(e) => setForm({ ...form, capacity: Number(e.target.value) })} />
            <input placeholder="Phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            <input placeholder="Notes / description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <button className="btn">Create lab</button>
          </div>
        </form>
      )}
      {labs.map((lab) => {
        const d = drafts[lab.id] || {}
        return (
          <div className="card" key={lab.id} style={{ marginBottom: 12 }}>
            <div className="toolbar" style={{ marginBottom: 8 }}>
              <strong>{lab.name}</strong>
              <span className="muted">{lab.online_count}/{lab.machine_count} hosts online</span>
              {lab.protected && <span className="badge">Protected</span>}
            </div>
            <div className="toolbar">
              <input placeholder="Name" value={d.name ?? ''} disabled={!canEdit || lab.protected} onChange={(e) => setDraft(lab.id, { name: e.target.value })} />
              <input placeholder="Code" value={d.code ?? ''} disabled={!canEdit} onChange={(e) => setDraft(lab.id, { code: e.target.value })} />
              <input placeholder="Building" value={d.building ?? ''} disabled={!canEdit} onChange={(e) => setDraft(lab.id, { building: e.target.value })} />
              <input placeholder="Floor" value={d.floor ?? ''} disabled={!canEdit} onChange={(e) => setDraft(lab.id, { floor: e.target.value })} />
              <input placeholder="Room" value={d.room ?? ''} disabled={!canEdit} onChange={(e) => setDraft(lab.id, { room: e.target.value })} />
              <input placeholder="Capacity" type="number" min={0} value={d.capacity ?? 0} disabled={!canEdit} onChange={(e) => setDraft(lab.id, { capacity: Number(e.target.value) })} />
              <input placeholder="Phone" value={d.phone ?? ''} disabled={!canEdit} onChange={(e) => setDraft(lab.id, { phone: e.target.value })} />
              <input placeholder="Notes" value={d.description ?? ''} disabled={!canEdit} onChange={(e) => setDraft(lab.id, { description: e.target.value })} />
              {canEdit && <button className="btn secondary" type="button" onClick={() => saveLab(lab.id)}>Save</button>}
              {canEdit && !lab.protected && <button className="btn danger" type="button" onClick={() => removeLab(lab)}>Delete</button>}
            </div>
          </div>
        )
      })}
      <div className="card" style={{ padding: 0, overflowX: 'auto', marginTop: 16 }}>
        <h3 className="section-title" style={{ padding: 16, margin: 0 }}>Machines in labs</h3>
        <table>
          <thead>
            <tr><th>Machine ID</th><th>Hostname</th><th>Lab</th><th>Approved</th><th></th></tr>
          </thead>
          <tbody>
            {machines.map((m) => {
              const d = hostDrafts[m.id] || { display_name: '', lab_id: '', approved: true }
              return (
                <tr key={m.id}>
                  <td className="mono">{m.inventory_id || '—'}</td>
                  <td>{m.hostname}</td>
                  <td>
                    <select className="lab-assign" value={d.lab_id} disabled={!canEdit} onChange={(e) => setHostDrafts({ ...hostDrafts, [m.id]: { ...d, lab_id: e.target.value } })}>
                      {!d.lab_id && <option value="">Pick a lab</option>}
                      {labs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                    </select>
                  </td>
                  <td>
                    <input type="checkbox" checked={d.approved} disabled={!canEdit} onChange={(e) => setHostDrafts({ ...hostDrafts, [m.id]: { ...d, approved: e.target.checked } })} />
                  </td>
                  <td>{canEdit && <button className="btn secondary" type="button" onClick={() => saveMachine(m.id)}>Save</button>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}
