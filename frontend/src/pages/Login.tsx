import type { FormEvent } from 'react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, setSession } from '../api'

export default function Login() {
  const nav = useNavigate()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setErr('')
    try {
      const data = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
      setSession(data)
      nav('/')
    } catch (ex: any) {
      setErr(ex.message || 'Login failed')
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={onSubmit}>
        <div className="brand" style={{ marginBottom: 18 }}>
          <div className="brand-mark">LW</div>
          <div>
            <h2 style={{ margin: 0 }}>LabWatch</h2>
            <p className="muted">Institute lab monitoring</p>
          </div>
        </div>
        <div className="field">
          <label>Username</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </div>
        <div className="field">
          <label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </div>
        {err && <div className="err">{err}</div>}
        <button className="btn" type="submit">Sign in</button>
      </form>
    </div>
  )
}
