import type { FormEvent } from 'react'
import { useState } from 'react'
import { api, currentUser } from '../api'

export default function Account() {
  const user = currentUser()
  const [currentPassword, setCurrentPassword] = useState('')
  const [nextPassword, setNextPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  async function save(e: FormEvent) {
    e.preventDefault()
    setErr('')
    setMsg('')
    if (nextPassword !== confirm) {
      setErr('New passwords do not match')
      return
    }
    try {
      await api('/api/auth/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: currentPassword, new_password: nextPassword }),
      })
      setCurrentPassword('')
      setNextPassword('')
      setConfirm('')
      setMsg('Password updated')
    } catch (e: any) {
      setErr(e.message)
    }
  }

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Account</h2>
          <p>Signed in as {user?.username} ({user?.role})</p>
        </div>
      </div>
      {err && <p className="err">{err}</p>}
      {msg && <p className="muted">{msg}</p>}
      <form className="card" style={{ maxWidth: 420 }} onSubmit={save}>
        <div className="field">
          <label>Current password</label>
          <input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required />
        </div>
        <div className="field">
          <label>New password</label>
          <input type="password" value={nextPassword} onChange={(e) => setNextPassword(e.target.value)} required minLength={8} />
        </div>
        <div className="field">
          <label>Confirm new password</label>
          <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required minLength={8} />
        </div>
        <button className="btn">Change password</button>
      </form>
    </>
  )
}
