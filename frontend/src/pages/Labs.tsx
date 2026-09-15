import type { FormEvent } from 'react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { currentUser } from '../api'

export default function Labs() {
  const [labs, setLabs] = useState<any[]>([])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const role = currentUser()?.role
  const canEdit = role === 'ADMIN' || role === 'OPERATOR'

  function load() {
    api('/api/labs').then(setLabs)
  }
  useEffect(load, [])

  async function create(e: FormEvent) {
    e.preventDefault()
    await api('/api/labs', { method: 'POST', body: JSON.stringify({ name, description }) })
    setName(''); setDescription(''); load()
  }

  async function rename(lab: any) {
    const next = prompt('Lab name', lab.name)
    if (!next) return
    await api(`/api/labs/${lab.id}`, { method: 'PATCH', body: JSON.stringify({ name: next }) })
    load()
  }

  return (
    <>
      <div className="topbar"><div><h2>Labs</h2><p>Group machines by room or research group</p></div></div>
      {canEdit && (
        <form className="card toolbar" onSubmit={create}>
          <input placeholder="Lab name" value={name} onChange={(e) => setName(e.target.value)} required />
          <input placeholder="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
          <button className="btn">Create lab</button>
        </form>
      )}
      <div className="grid stats">
        {labs.map((l) => (
          <div className="card" key={l.id}>
            <h3 style={{ marginTop: 0 }}>{l.name}</h3>
            <p className="muted">{l.description || '—'}</p>
            <p className="mono">{l.online_count} / {l.machine_count} online</p>
            {canEdit && <button className="btn secondary" onClick={() => rename(l)}>Rename</button>}
          </div>
        ))}
      </div>
    </>
  )
}
