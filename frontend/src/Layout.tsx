import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api, clearSession, currentUser } from './api'
import { useEffect, useState } from 'react'

const links = [
  ['/', 'Dashboard'],
  ['/machines', 'Machines'],
  ['/alerts', 'Alerts'],
  ['/admin', 'Admin'],
]

export default function Layout() {
  const nav = useNavigate()
  const location = useLocation()
  const user = currentUser()
  const [theme, setTheme] = useState(localStorage.getItem('lw_theme') || 'dark')
  const [unread, setUnread] = useState(0)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('lw_theme', theme)
  }, [theme])

  useEffect(() => {
    function loadCount() {
      api<{ active?: number }>('/api/alerts/summary')
        .then((s) => setUnread(s.active || 0))
        .catch(() => undefined)
    }
    loadCount()
    const timer = window.setInterval(loadCount, 10000)
    window.addEventListener('lw-alerts-changed', loadCount)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('lw-alerts-changed', loadCount)
    }
  }, [location.pathname])

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
            if (label === 'Admin' && user?.role !== 'ADMIN') return null
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
