import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ago, api, bytes, fmt } from '../api'
import { StatusBadge } from '../Layout'

const TABS = ['Overview', 'CPU', 'Memory', 'GPU', 'Storage', 'Network', 'Motherboard', 'History', 'Metrics', 'Events', 'Logs'] as const
const RANGES = [
  ['1h', '1 hour'],
  ['6h', '6 hours'],
  ['24h', '24 hours'],
  ['7d', '7 days'],
  ['30d', '30 days'],
]

function Meter({ value }: { value?: number | null }) {
  if (value == null) return <div className="muted">Unknown / Not reported</div>
  const cls = value >= 90 ? 'crit' : value >= 75 ? 'warn' : ''
  return (
    <div>
      <div className="mono">{value.toFixed(1)}%</div>
      <div className={`meter ${cls}`}><i style={{ width: `${Math.min(value, 100)}%` }} /></div>
    </div>
  )
}

function Kv({ label, value }: { label: string; value: unknown }) {
  return (
    <>
      <span>{label}</span>
      <div>{fmt(value)}</div>
    </>
  )
}

export default function MachineDetail() {
  const { id } = useParams()
  const [tab, setTab] = useState<(typeof TABS)[number]>('Overview')
  const [machine, setMachine] = useState<any>(null)
  const [hw, setHw] = useState<any>(null)
  const [events, setEvents] = useState<any[]>([])
  const [logs, setLogs] = useState<any[]>([])
  const [metrics, setMetrics] = useState<any>(null)
  const [range, setRange] = useState('24h')
  const [labs, setLabs] = useState<any[]>([])

  useEffect(() => {
    if (!id) return
    api(`/api/machines/${id}`).then(setMachine)
    api(`/api/machines/${id}/hardware`).then(setHw)
    api(`/api/machines/${id}/events`).then(setEvents)
    api(`/api/machines/${id}/logs`).then(setLogs)
    api('/api/labs').then(setLabs)
  }, [id])

  useEffect(() => {
    if (!id || tab !== 'Metrics') return
    api(`/api/machines/${id}/metrics?range=${range}`).then(setMetrics)
  }, [id, tab, range])

  const mem = hw?.memory
  const cpu = hw?.cpu

  if (!machine) return <p className="muted">Loading machine…</p>

  return (
    <>
      <div className="topbar">
        <div>
          <h2>{machine.display_name || machine.hostname}</h2>
          <p>
            {machine.lab_name || 'Unassigned'} · {machine.os_name}
            {machine.is_virtual ? ' · Virtual machine' : ' · Physical machine'}
          </p>
        </div>
        <StatusBadge status={machine.status} />
      </div>
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {tab === 'Overview' && (
        <div className="split">
          <div className="card">
            <h3 className="section-title">Identity</h3>
            <div className="kv">
              <Kv label="Hostname" value={machine.hostname} />
              <Kv label="Current IP" value={machine.current_ip} />
              <Kv label="All IPs" value={(machine.current_ips || []).join(', ') || machine.current_ip} />
              <Kv label="Previous IP" value={machine.previous_ip} />
              <Kv label="Architecture" value={machine.architecture} />
              <Kv label="Last seen" value={ago(machine.last_seen_at)} />
              <Kv label="System UUID" value={machine.system_uuid} />
              <Kv label="Machine UUID" value={machine.machine_uuid} />
              <Kv label="Agent" value={`${machine.agent?.status || '—'} ${machine.agent?.version || ''}`} />
              <Kv label="Virtualization" value={machine.is_virtual ? machine.virtualization : 'Physical'} />
            </div>
          </div>
          <div className="card">
            <h3 className="section-title">Snapshot</h3>
            <div className="kv">
              <Kv label="CPU" value={cpu?.model} />
              <Kv label="RAM installed" value={bytes(mem?.total_physical_bytes)} />
              <Kv label="RAM slots" value={mem?.slot_count ?? 'Unknown / Not reported'} />
              <Kv label="GPUs" value={machine.gpu_count} />
              <Kv label="Disks" value={hw?.storage?.disks?.length ?? '—'} />
            </div>
            <div className="field" style={{ marginTop: 16 }}>
              <label>Move to lab</label>
              <select
                value={machine.lab_id || ''}
                onChange={async (e) => {
                  await api(`/api/machines/${machine.id}`, { method: 'PATCH', body: JSON.stringify({ lab_id: e.target.value || null }) })
                  const m = await api(`/api/machines/${machine.id}`)
                  setMachine(m)
                }}
              >
                <option value="">Unassigned</option>
                {labs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </div>
          </div>
        </div>
      )}

      {tab === 'CPU' && cpu && (
        <div className="card">
          <div className="kv">
            <Kv label="Manufacturer" value={cpu.manufacturer} />
            <Kv label="Model" value={cpu.model} />
            <Kv label="Family" value={cpu.family} />
            <Kv label="Architecture" value={cpu.architecture} />
            <Kv label="Sockets" value={cpu.physical_sockets} />
            <Kv label="Physical cores" value={cpu.physical_cores} />
            <Kv label="Logical processors" value={cpu.logical_processors} />
            <Kv label="Base frequency" value={cpu.base_frequency_mhz ? `${cpu.base_frequency_mhz} MHz` : null} />
            <Kv label="Current frequency" value={cpu.current_frequency_mhz ? `${cpu.current_frequency_mhz} MHz` : null} />
            <Kv label="Temperature" value={cpu.temperature_c != null ? `${cpu.temperature_c} °C` : null} />
            <Kv label="Utilization" value={cpu.usage_pct != null ? `${cpu.usage_pct}%` : null} />
            <Kv label="Load average" value={cpu.load_avg_1 != null ? `${cpu.load_avg_1} / ${cpu.load_avg_5} / ${cpu.load_avg_15}` : null} />
            <Kv label="Uptime" value={cpu.uptime_seconds != null ? `${Math.floor(cpu.uptime_seconds / 3600)} h` : null} />
          </div>
          {cpu.notes?.length > 0 && <p className="muted">{cpu.notes.join(' ')}</p>}
        </div>
      )}

      {tab === 'Memory' && mem && (
        <div className="grid">
          <div className="grid stats">
            <div className="card stat"><div className="label">Slots</div><div className="value">{mem.slot_count ?? '—'}</div></div>
            <div className="card stat"><div className="label">Occupied</div><div className="value">{mem.occupied_slots ?? '—'}</div></div>
            <div className="card stat"><div className="label">Free</div><div className="value">{mem.free_slots ?? '—'}</div></div>
            <div className="card stat"><div className="label">Installed</div><div className="value" style={{ fontSize: 18 }}>{bytes(mem.total_physical_bytes)}</div></div>
            <div className="card stat"><div className="label">Maximum</div><div className="value" style={{ fontSize: 18 }}>{bytes(mem.max_supported_bytes)}</div></div>
            <div className="card stat"><div className="label">Usage</div><div className="value" style={{ fontSize: 18 }}>{mem.usage_pct != null ? `${mem.usage_pct.toFixed(1)}%` : '—'}</div></div>
          </div>
          <div className="card">
            <h3 className="section-title">RAM slots · topology {mem.topology_status}</h3>
            {mem.unlocated_empty_slots ? <p className="muted">{mem.unlocated_empty_slots} additional empty slot(s) without firmware locators.</p> : null}
            <div className="ram-grid">
              {(mem.slots || []).map((s: any) => (
                <div key={s.slot_locator} className={`ram-slot ${s.occupied ? 'occupied' : ''}`}>
                  <div className="loc">{s.slot_locator}{s.bank_locator ? ` · ${s.bank_locator}` : ''}</div>
                  <div className="cap">{s.occupied ? bytes(s.capacity_bytes) : 'EMPTY'}</div>
                  <div className="meta">
                    {s.occupied
                      ? [s.manufacturer, s.memory_type, s.speed_mts ? `${s.speed_mts} MT/s` : null].filter(Boolean).join(' · ')
                      : 'No module installed'}
                  </div>
                  {s.occupied && <div className="meta">{[s.part_number, s.serial_number, s.form_factor, s.ecc].filter((x: any) => x && x !== 'Unknown / Not reported').join(' · ')}</div>}
                </div>
              ))}
            </div>
            {(!mem.slots || mem.slots.length === 0) && <p className="muted">Unknown / Not reported — firmware/OS did not expose DIMM topology.</p>}
            {mem.notes?.length > 0 && <p className="muted">{mem.notes.join(' ')}</p>}
            <p className="muted" style={{ marginTop: 12 }}>
              Usage: {bytes(mem.used_bytes)} / {bytes(mem.total_physical_bytes)} available {bytes(mem.available_bytes)}
            </p>
          </div>
        </div>
      )}

      {tab === 'GPU' && (
        <div className="grid">
          <div className="card">
            <h3 className="section-title">PCIe / GPU slots · {hw?.pcie?.topology_status}</h3>
            <p className="muted">{hw?.pcie?.topology_note || ''}</p>
            {hw?.pcie?.gpu_capable_total != null && (
              <p>GPU-capable slots: {hw.pcie.gpu_capable_total} · occupied {hw.pcie.gpu_capable_occupied} · free {hw.pcie.gpu_capable_free}</p>
            )}
            {hw?.pcie?.gpu_capable_total == null && <p className="muted">GPU-capable slot count not exposed; x16 PCIe is not assumed to be a GPU slot.</p>}
            {(hw?.pcie?.slots || []).length > 0 && (
              <table>
                <thead><tr><th>Slot</th><th>Type</th><th>Width</th><th>Usage</th><th>GPU-capable</th><th>Device</th></tr></thead>
                <tbody>
                  {hw.pcie.slots.map((s: any) => (
                    <tr key={s.slot_designation}>
                      <td>{s.slot_designation}</td>
                      <td>{s.slot_type}</td>
                      <td>{s.width}</td>
                      <td>{s.current_usage}</td>
                      <td>{s.is_gpu_capable == null ? 'Unknown' : s.is_gpu_capable ? 'Yes' : 'No'}</td>
                      <td>{s.attached_device}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="gpu-grid">
            {(hw?.gpus || []).map((g: any) => (
              <div className="card" key={g.index}>
                <h3 style={{ marginTop: 0 }}>GPU {g.index} · {g.model}</h3>
                <div className="muted">{g.vendor} · {g.slot_designation}</div>
                <p>Temperature: {g.temperature_c != null ? `${g.temperature_c} °C` : 'Unknown / Not reported'}</p>
                <p>Utilization: {g.utilization_pct != null ? `${g.utilization_pct}%` : 'Unknown / Not reported'}</p>
                <Meter value={g.utilization_pct} />
                <p>VRAM: {g.vram_bytes ? bytes(g.vram_bytes) : 'Unknown / Not reported'}</p>
                <p>Power: {g.power_w != null ? `${g.power_w} W` : 'Unknown / Not reported'}</p>
                <p>Driver: {fmt(g.driver_version)}</p>
                <p>PCI: {fmt(g.pci_bus)} · Serial {fmt(g.serial_number)}</p>
              </div>
            ))}
            {(!hw?.gpus || hw.gpus.length === 0) && <div className="card muted">No GPUs detected.</div>}
          </div>
        </div>
      )}

      {tab === 'Storage' && (
        <div className="card">
          <h3 className="section-title">Physical disks</h3>
          <table>
            <thead><tr><th>Name</th><th>Model</th><th>Serial</th><th>Capacity</th><th>Interface</th><th>Media</th><th>SMART</th><th>Temp</th></tr></thead>
            <tbody>
              {(hw?.storage?.disks || []).map((d: any) => (
                <tr key={d.name + d.serial_number}>
                  <td>{d.name}</td><td>{d.model}</td><td className="mono">{d.serial_number}</td>
                  <td>{bytes(d.capacity_bytes)}</td><td>{d.interface}</td><td>{d.media_type}</td>
                  <td>{d.smart_status}</td><td>{d.temperature_c != null ? `${d.temperature_c}°C` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3 className="section-title" style={{ marginTop: 24 }}>Filesystems</h3>
          {(hw?.storage?.filesystems || []).map((f: any) => (
            <div key={f.mountpoint} style={{ marginBottom: 10 }}>
              <div>{f.mountpoint} · {f.fstype} · {bytes(f.used_bytes)} / {bytes(f.total_bytes)}</div>
              <Meter value={f.total_bytes ? (100 * f.used_bytes) / f.total_bytes : null} />
            </div>
          ))}
        </div>
      )}

      {tab === 'Network' && (
        <div className="card">
          <table>
            <thead><tr><th>Adapter</th><th>MAC</th><th>IPv4</th><th>Status</th><th>Speed</th></tr></thead>
            <tbody>
              {(hw?.network || []).map((n: any) => (
                <tr key={n.name}>
                  <td>{n.name}</td>
                  <td className="mono">{n.mac}</td>
                  <td className="mono">{(n.ipv4 || []).join(', ')}</td>
                  <td>{n.is_up ? 'up' : 'down'}</td>
                  <td>{n.speed_mbps ? `${n.speed_mbps} Mbps` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'Motherboard' && (
        <div className="split">
          <div className="card">
            <h3 className="section-title">Motherboard</h3>
            <div className="kv">
              <Kv label="Manufacturer" value={hw?.motherboard?.manufacturer} />
              <Kv label="Model" value={hw?.motherboard?.model} />
              <Kv label="Serial" value={hw?.motherboard?.serial_number} />
              <Kv label="Version" value={hw?.motherboard?.version} />
            </div>
          </div>
          <div className="card">
            <h3 className="section-title">BIOS / system</h3>
            <div className="kv">
              <Kv label="Vendor" value={hw?.bios?.vendor} />
              <Kv label="Version" value={hw?.bios?.version} />
              <Kv label="Release date" value={hw?.bios?.release_date} />
              <Kv label="System manufacturer" value={hw?.bios?.system_manufacturer} />
              <Kv label="System model" value={hw?.bios?.system_model} />
              <Kv label="System serial" value={hw?.bios?.system_serial} />
            </div>
          </div>
        </div>
      )}

      {tab === 'History' && (
        <div className="card">
          <h3 className="section-title">Hardware history</h3>
          <div className="timeline">
            {events.map((e) => (
              <div className="tl-item" key={e.id}>
                <time>{new Date(e.created_at).toLocaleString()}</time>
                <div>
                  <span className={`badge ${e.severity}`}>{e.event_type.replaceAll('_', ' ')}</span>
                  <div>{e.summary}</div>
                  <div className="muted">{e.component_path} · {e.detected_by}</div>
                </div>
              </div>
            ))}
            {events.length === 0 && <p className="muted">No recorded hardware events yet. Registration appears after the first inventory.</p>}
          </div>
        </div>
      )}

      {tab === 'Metrics' && (
        <div className="card">
          <div className="toolbar">
            {RANGES.map(([k, l]) => (
              <button key={k} className={`btn secondary ${range === k ? '' : ''}`} onClick={() => setRange(k)}>{l}</button>
            ))}
          </div>
          {!metrics && <p className="muted">Loading metrics…</p>}
          {metrics && <Charts metrics={metrics} />}
        </div>
      )}

      {tab === 'Events' && (
        <div className="card">
          {events.map((e) => (
            <div key={e.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--line)' }}>
              <span className={`badge ${e.severity}`}>{e.event_type}</span> {e.summary}
              <div className="muted">{ago(e.created_at)}</div>
            </div>
          ))}
        </div>
      )}

      {tab === 'Logs' && (
        <div className="card">
          {logs.map((l) => (
            <div key={l.id} style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
              <span className="badge">{l.level}</span> {l.message}
              <div className="muted">{ago(l.created_at)}</div>
            </div>
          ))}
          {logs.length === 0 && <p className="muted">No agent logs.</p>}
        </div>
      )}
    </>
  )
}

function Charts({ metrics }: { metrics: any }) {
  const samples = useMemo(
    () =>
      (metrics.samples || []).map((s: any) => ({
        ...s,
        t: new Date(s.collected_at).toLocaleTimeString(),
      })),
    [metrics],
  )
  const gpus = metrics.gpus || []
  const gpuIndexes = Array.from(new Set(gpus.map((g: any) => g.index))) as number[]
  return (
    <div className="grid">
      <ChartBlock title="CPU usage %" data={samples} dataKey="cpu_usage_pct" />
      <ChartBlock title="CPU temperature °C" data={samples} dataKey="cpu_temp_c" />
      <ChartBlock title="RAM usage %" data={samples} dataKey="ram_usage_pct" />
      <ChartBlock title="Network TX B/s" data={samples} dataKey="net_tx_bps" />
      <ChartBlock title="Network RX B/s" data={samples} dataKey="net_rx_bps" />
      {gpuIndexes.map((idx) => {
        const series = gpus.filter((g: any) => g.index === idx).map((g: any) => ({ ...g, t: new Date(g.collected_at).toLocaleTimeString() }))
        return (
          <div key={idx}>
            <ChartBlock title={`GPU ${idx} utilization %`} data={series} dataKey="utilization_pct" />
            <ChartBlock title={`GPU ${idx} temperature °C`} data={series} dataKey="temperature_c" />
            <ChartBlock title={`GPU ${idx} power W`} data={series} dataKey="power_w" />
          </div>
        )
      })}
    </div>
  )
}

function ChartBlock({ title, data, dataKey }: { title: string; data: any[]; dataKey: string }) {
  return (
    <div style={{ height: 220 }}>
      <h3 className="section-title">{title}</h3>
      {data.length === 0 ? (
        <p className="muted">No samples in this range.</p>
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={data}>
            <XAxis dataKey="t" hide />
            <YAxis width={40} />
            <Tooltip />
            <Line type="monotone" dataKey={dataKey} stroke="#3dbe9a" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
