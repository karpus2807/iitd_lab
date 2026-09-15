import type { FormEvent } from 'react'
import { useEffect, useState } from 'react'
import { api, currentUser } from '../api'

type Lab = {
  id: string
  name: string
  description: string
  building?: string
  room?: string
  machine_count: number
  online_count: number
  protected?: boolean
}

type Machine = {
  id: string
  hostname: string
  display_name: string
  lab_id?: string | null
  status: string
}

export default function Infra() {
  const role = currentUser()?.role
  const canEdit = role === 'ADMIN' || role === 'OPERATOR'
  const [labs, setLabs] = useState<Lab[]>([])
  const [machines, setMachines] = useState<Machine[]>([])
  const [drafts, setDrafts] = useState<Record<string, Partial<Lab>>>({})
  const [hostDrafts, setHostDrafts] = useState<Record<string, { display_name: string; lab_id: string }>>({})
  const [form, setForm] = useState({ name: '', building: '', room: '', description: '' })
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  async function load() {
    const [labRows, hostRows] = await Promise.all([api<Lab[]>('/api/labs'), api<Machine[]>('/api/machines')])
    setLabs(labRows)
    setMachines(hostRows)
    const next: Record<string, Partial<Lab>> = {}
    labRows.forEach((l) => { next[l.id] = { name: l.name, building: l.building || '', room: l.room || '', description: l.description || '' } })
    setDrafts(next)
    const hosts: Record<string, { display_name: string; lab_id: string }> = {}
    hostRows.forEach((m) => { hosts[m.id] = { display_name: m.display_name || '', lab_id: m.lab_id || '' } })
    setHostDrafts(hosts)
  }

  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])

  async function create(e: FormEvent) {
    e.preventDefault()
    setErr('')
    await api('/api/labs', { method: 'POST', body: JSON.stringify(form) })
    setForm({ name: '', building: '', room: '', description: '' })
    setMsg('Lab created')
    await load()
  }

  async function saveLab(id: string) {
    setErr('')
    await api(`/api/labs/${id}`, { method: 'PATCH', body: JSON.stringify(drafts[id]) })
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
    await api(`/api/machines/${id}`, { method: 'PATCH', body: JSON.stringify({ display_name: d.display_name, lab_id: d.lab_id || null }) })
    setMsg('Machine saved')
    await load()
  }

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Infrastructure</h2>
          <p>Edit lab names, building, room, and assign machines. Seed names like DAIR LAB can be renamed or removed.</p>
        </div>
      </div>
      {err && <p className="err">{err}</p>}
      {msg && <p className="muted">{msg}</p>}
      {canEdit && (
        <form className="card toolbar" onSubmit={create}>
          <input placeholder="Lab name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          <input placeholder="Building" value={form.building} onChange={(e) => setForm({ ...form, building: e.target.value })} />
          <input placeholder="Room" value={form.room} onChange={(e) => setForm({ ...form, room: e.target.value })} />
          <input placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <button className="btn">Add lab</button>
        </form>
      )}
      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        <table>
          <thead>
            <tr><th>Name</th><th>Building</th><th>Room</th><th>Description</th><th>Hosts</th><th></th></tr>
          </thead>
          <tbody>
            {labs.map((lab) => {
              const d = drafts[lab.id] || {}
              return (
                <tr key={lab.id}>
                  <td><input value={d.name ?? lab.name} disabled={!canEdit} onChange={(e) => setDrafts({ ...drafts, [lab.id]: { ...d, name: e.target.value } })} /></td>
                  <td><input value={d.building ?? ''} disabled={!canEdit} onChange={(e) => setDrafts({ ...drafts, [lab.id]: { ...d, building: e.target.value } })} /></td>
                  <td><input value={d.room ?? ''} disabled={!canEdit} onChange={(e) => setDrafts({ ...drafts, [lab.id]: { ...d, room: e.target.value } })} /></td>
                  <td><input value={d.description ?? ''} disabled={!canEdit} onChange={(e) => setDrafts({ ...drafts, [lab.id]: { ...d, description: e.target.value } })} /></td>
                  <td className="mono">{lab.online_count}/{lab.machine_count}</td>
                  <td className="row-actions">
                    {canEdit && <button className="btn secondary" type="button" onClick={() => saveLab(lab.id)}>Save</button>}
                    {canEdit && !lab.protected && <button className="btn danger" type="button" onClick={() => removeLab(lab)}>Delete</button>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="card" style={{ padding: 0, overflowX: 'auto', marginTop: 16 }}>
        <h3 className="section-title" style={{ padding: 16, margin: 0 }}>Machines</h3>
        <table>
          <thead>
            <tr><th>Hostname</th><th>Display name</th><th>Lab</th><th></th></tr>
          </thead>
          <tbody>
            {machines.map((m) => {
              const d = hostDrafts[m.id] || { display_name: '', lab_id: '' }
              return (
                <tr key={m.id}>
                  <td>{m.hostname}</td>
                  <td><input value={d.display_name} disabled={!canEdit} onChange={(e) => setHostDrafts({ ...hostDrafts, [m.id]: { ...d, display_name: e.target.value } })} /></td>
                  <td>
                    <select value={d.lab_id} disabled={!canEdit} onChange={(e) => setHostDrafts({ ...hostDrafts, [m.id]: { ...d, lab_id: e.target.value } })}>
                      <option value="">Unassigned</option>
                      {labs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                    </select>
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
