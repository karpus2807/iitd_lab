import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ago, api } from '../api'

export default function Dashboard() {
  const [data, setData] = useState<any>(null)
  const [err, setErr] = useState('')
  const nav = useNavigate()

  useEffect(() => {
    api('/api/dashboard/summary').then(setData).catch((e) => setErr(e.message))
  }, [])

  if (err) return <p className="err">{err}</p>
  if (!data) return <p className="muted">Loading overview…</p>

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Lab monitoring</h2>
          <p>Fleet status across all computer labs</p>
        </div>
      </div>
      <div className="grid stats">
        <div className="card stat"><div className="label">Machines</div><div className="value">{data.machines}</div></div>
        <div className="card stat online"><div className="label">Online</div><div className="value">{data.online}</div></div>
        <div className="card stat offline"><div className="label">Offline</div><div className="value">{data.offline}</div></div>
        <div className="card stat alert"><div className="label">Alerts</div><div className="value">{data.alerts}</div></div>
        <div className="card stat"><div className="label">GPUs</div><div className="value">{data.gpus}</div></div>
        <div className="card stat"><div className="label">HW changes</div><div className="value">{data.machines_with_hardware_changes}</div></div>
      </div>
      <div className="split" style={{ marginTop: 16 }}>
        <div className="card">
          <h3 className="section-title">Labs</h3>
          <table>
            <thead><tr><th>Lab</th><th>Machines</th><th>Online</th></tr></thead>
            <tbody>
              {data.labs.map((l: any) => (
                <tr key={l.id} className="clickable" onClick={() => nav(`/machines?lab=${l.id}`)}>
                  <td>{l.name}</td>
                  <td className="mono">{l.machines}</td>
                  <td className="mono">{l.online}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3 className="section-title">Recent hardware changes</h3>
          {data.recent_changes.length === 0 && <p className="muted">No hardware-change events yet.</p>}
          <div className="timeline">
            {data.recent_changes.map((e: any) => (
              <div className="tl-item" key={e.id} style={{ gridTemplateColumns: '1fr' }}>
                <div>
                  <strong>{e.hostname}</strong> · <span className={`badge ${e.severity}`}>{e.event_type.replaceAll('_', ' ')}</span>
                  <div className="muted">{e.summary}</div>
                  <div className="muted">{ago(e.created_at)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
