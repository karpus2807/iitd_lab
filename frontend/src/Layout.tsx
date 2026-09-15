import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { clearSession, currentUser } from './api'
import { useEffect, useState } from 'react'

const links = [
  ['/', 'Dashboard'],
  ['/machines', 'Machines'],
  ['/labs', 'Labs'],
  ['/updates', 'Updates'],
  ['/alerts', 'Alerts'],
  ['/admin', 'Admin'],
]

export default function Layout() {
  const nav = useNavigate()
  const user = currentUser()
  const [theme, setTheme] = useState(localStorage.getItem('lw_theme') || 'dark')
  const [unread, setUnread] = useState(0)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('lw_theme', theme)
  }, [theme])

  useEffect(() => {
    fetch('/api/notifications?unread=true', { headers: { Authorization: `Bearer ${localStorage.getItem('lw_access')}` } })
      .then((r) => (r.ok ? r.json() : []))
      .then((rows) => setUnread(Array.isArray(rows) ? rows.length : 0))
      .catch(() => undefined)
  }, [])

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">LW</div>
          <div>
            <h1>LabWatch</h1>
            <p>Hardware & assets</p>
          </div>
        </div>
        <nav className="nav">
          {links.map(([to, label]) => {
            if ((label === 'Updates' || label === 'Admin') && user?.role !== 'ADMIN') return null
            return (
              <NavLink key={to} to={to} end={to === '/' || to === '/admin'}>
                {label}
                {label === 'Alerts' && unread > 0 ? ` (${unread})` : ''}
              </NavLink>
            )
          })}
        </nav>
        <div className="sidebar-foot">
          <div>{user?.username} · {user?.role}</div>
          <button className="btn secondary" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? 'Light mode' : 'Dark mode'}
          </button>
          <button className="btn secondary" onClick={() => nav('/account')}>
            Password
          </button>
          <button
            className="btn secondary"
            onClick={() => {
              clearSession()
              nav('/login')
            }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <section className="main">
        <Outlet />
      </section>
    </div>
  )
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge ${status}`}>
      <i className="dot" />
      {status.replaceAll('_', ' ')}
    </span>
  )
}
