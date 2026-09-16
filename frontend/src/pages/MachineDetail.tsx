import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ago, api, bytes, currentUser, isBlank } from '../api'
import { StatusBadge } from '../Layout'

const TABS = ['Overview', 'CPU', 'Memory', 'GPU', 'Storage', 'Network', 'Motherboard', 'History', 'Metrics', 'Events', 'Logs'] as const
const RANGES = [
  ['1h', '1 hour'],
  ['6h', '6 hours'],
  ['24h', '24 hours'],
  ['7d', '7 days'],
  ['30d', '30 days'],
]

function isSocMemory(mem: any) {
  const extra = mem?.extra || {}
  const notes = (mem?.notes || []).join(' ').toLowerCase()
  return (
    mem?.topology_status === 'SOC' ||
    extra.memory_kind === 'unified' ||
    extra.form_factor === 'soldered' ||
    notes.includes('soc') ||
    notes.includes('unified')
  )
}

function isSocGpu(g: any) {
  const extra = g?.extra || {}
  return extra.memory_kind === 'unified' || extra.bus === 'soc' || extra.platform === 'jetson'
}

function isSocPcie(pcie: any, gpus: any[]) {
  return pcie?.topology_status === 'SOC' || (gpus || []).some(isSocGpu)
}

function Meter({ value }: { value?: number | null }) {
  if (value == null) return null
  const cls = value >= 90 ? 'crit' : value >= 75 ? 'warn' : ''
  return (
    <div>
      <div className="mono">{value.toFixed(1)}%</div>
      <div className={`meter ${cls}`}><i style={{ width: `${Math.min(value, 100)}%` }} /></div>
    </div>
  )
}

function Kv({ label, value }: { label: string; value: unknown }) {
  if (isBlank(value)) return null
  return (
    <>
      <span>{label}</span>
      <div>{String(value)}</div>
    </>
  )
}

function Stat({ label, value }: { label: string; value?: ReactNode }) {
  if (value == null || value === '' || value === false) return null
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="value" style={{ fontSize: 18 }}>{value}</div>
    </div>
  )
}

function Show({ label, value, supported = true }: { label: string; value?: unknown; supported?: boolean }) {
  if (!supported) return null
  if (isBlank(value)) return <p>{label}: Not reported</p>
  return <p>{label}: {String(value)}</p>
}

export default function MachineDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const [tab, setTab] = useState<(typeof TABS)[number]>('Overview')
  const [machine, setMachine] = useState<any>(null)
  const [hw, setHw] = useState<any>(null)
  const [events, setEvents] = useState<any[]>([])
  const [logs, setLogs] = useState<any[]>([])
  const [metrics, setMetrics] = useState<any>(null)
  const [range, setRange] = useState('24h')
  const [labs, setLabs] = useState<any[]>([])
  const [err, setErr] = useState('')
  const [logLevel, setLogLevel] = useState('ALL')
  const [logQuery, setLogQuery] = useState('')
  const [busy, setBusy] = useState('')
  const canManage = ['ADMIN', 'OPERATOR'].includes(currentUser()?.role || '')

  useEffect(() => {
    if (!id) return
    api(`/api/machines/${id}`).then(setMachine)
    api(`/api/machines/${id}/hardware`).then(setHw)
    api(`/api/machines/${id}/events`).then(setEvents)
    api('/api/labs').then(setLabs)
  }, [id])

  useEffect(() => {
    if (!id || tab !== 'Logs') return
    const qs = new URLSearchParams()
    qs.set('limit', '500')
    if (logLevel && logLevel !== 'ALL') qs.set('level', logLevel)
    if (logQuery.trim()) qs.set('q', logQuery.trim())
    const load = () => api(`/api/machines/${id}/logs?${qs}`).then(setLogs).catch(() => undefined)
    load()
    const timer = window.setInterval(load, 8000)
    return () => window.clearInterval(timer)
  }, [id, tab, logLevel, logQuery])

  useEffect(() => {
    if (!id || tab !== 'Metrics') return
    const load = () => api(`/api/machines/${id}/metrics?range=${range}`).then(setMetrics).catch(() => undefined)
    load()
    const timer = window.setInterval(load, 8000)
    return () => window.clearInterval(timer)
  }, [id, tab, range])

  const mem = hw?.memory
  const cpu = hw?.cpu
  const socMem = isSocMemory(mem)
  const socPcie = isSocPcie(hw?.pcie, hw?.gpus)
  const memExtra = mem?.extra || {}

  if (!machine) return <p className="muted">Loading machine…</p>

  async function removeMachine() {
    const name = machine.inventory_id || machine.display_name || machine.hostname
    if (!confirm(`Remove ${name} from LabWatch? This deletes the host on the server. Uninstall the agent on the PC separately.`)) return
    setErr('')
    try {
      await api(`/api/machines/${machine.id}`, { method: 'DELETE' })
      nav('/machines')
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not remove machine')
    }
  }

  async function clearKind(kind: 'history' | 'events' | 'logs') {
    const labels = {
      history: 'hardware history',
      events: 'events',
      logs: 'logs',
    }
    if (!confirm(`Clear all ${labels[kind]} for this machine? This cannot be undone.`)) return
    setErr('')
    setBusy(kind)
    try {
      await api(`/api/machines/${machine.id}/${kind}`, { method: 'DELETE' })
      if (kind === 'logs') setLogs([])
      else setEvents([])
    } catch (e) {
      setErr(e instanceof Error ? e.message : `Could not clear ${labels[kind]}`)
    } finally {
      setBusy('')
    }
  }

  return (
    <>
      <div className="topbar">
        <div>
          <h2>{machine.inventory_id || machine.display_name || machine.hostname}</h2>
          <p>
            {machine.hostname}
            {machine.lab_name ? ` · ${machine.lab_name}` : ' · Unassigned'} · {machine.os_name}
            {machine.is_virtual ? ' · Virtual machine' : ' · Physical machine'}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <StatusBadge status={machine.status} />
          {canManage && (
            <button className="btn danger" type="button" onClick={removeMachine}>Remove from LabWatch</button>
          )}
        </div>
      </div>
      {err && <p className="err">{err}</p>}
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
              <Kv label="Agent" value={`${machine.agent?.status || ''} ${machine.agent?.version || ''}`.trim()} />
              <Kv label="Virtualization" value={machine.is_virtual ? machine.virtualization : 'Physical'} />
            </div>
          </div>
          <div className="card">
            <h3 className="section-title">Snapshot</h3>
            <div className="kv">
              <Kv label="CPU" value={cpu?.model} />
              <Kv label="RAM installed" value={bytes(mem?.total_physical_bytes)} />
              <Kv label="RAM layout" value={socMem ? 'Soldered / unified' : mem?.slot_count} />
              <Kv label="GPUs" value={machine.gpu_count} />
              <Kv label="Disks" value={hw?.storage?.disks?.length} />
            </div>
            {canManage && (
              <div className="field" style={{ marginTop: 16 }}>
                <label>Move to lab</label>
                <select
                  className="lab-assign"
                  value={machine.lab_id || ''}
                  onChange={async (e) => {
                    if (!e.target.value) return
                    await api(`/api/machines/${machine.id}`, { method: 'PATCH', body: JSON.stringify({ lab_id: e.target.value }) })
                    const m = await api(`/api/machines/${machine.id}`)
                    setMachine(m)
                  }}
                >
                  {!machine.lab_id && <option value="">Pick a lab</option>}
                  {labs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </div>
            )}
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
        </div>
      )}

      {tab === 'Memory' && mem && (
        <div className="grid">
          <div className="grid stats">
            {socMem ? (
              <>
                <Stat label="Layout" value="SoC unified" />
                <Stat label="Type" value={memExtra.memory_type} />
                <Stat label="Speed" value={memExtra.speed_mts ? `${memExtra.speed_mts} MT/s` : null} />
                <Stat label="Installed" value={bytes(mem.total_physical_bytes)} />
                <Stat label="Used" value={bytes(mem.used_bytes)} />
                <Stat label="Available" value={bytes(mem.available_bytes)} />
                <Stat label="Usage" value={mem.usage_pct != null ? `${mem.usage_pct.toFixed(1)}%` : null} />
              </>
            ) : (
              <>
                <Stat label="Slots" value={mem.slot_count} />
                <Stat label="Occupied" value={mem.occupied_slots} />
                <Stat label="Free" value={mem.free_slots} />
                <Stat label="Installed" value={bytes(mem.total_physical_bytes)} />
                <Stat label="Maximum" value={bytes(mem.max_supported_bytes)} />
                <Stat label="Usage" value={mem.usage_pct != null ? `${mem.usage_pct.toFixed(1)}%` : null} />
              </>
            )}
          </div>
          <div className="card">
            {socMem ? (
              <>
                <h3 className="section-title">Unified / soldered memory</h3>
                <p className="muted">This board has no DIMM map. RAM is on-package with the SoC.</p>
                <div className="kv" style={{ marginTop: 12 }}>
                  <Kv label="Installed" value={bytes(mem.total_physical_bytes)} />
                  <Kv label="Used" value={bytes(mem.used_bytes)} />
                  <Kv label="Available" value={bytes(mem.available_bytes)} />
                  <Kv label="Type" value={memExtra.memory_type} />
                  <Kv label="Form factor" value={memExtra.form_factor} />
                  <Kv label="EMC / speed" value={memExtra.speed_mts ? `${memExtra.speed_mts} MT/s` : (memExtra.emc_clock_mhz ? `${memExtra.emc_clock_mhz} MHz` : null)} />
                </div>
                <Meter value={mem.usage_pct} />
              </>
            ) : (
              <>
                <h3 className="section-title">RAM slots</h3>
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
                      {s.occupied && (
                        <div className="meta">
                          {[s.part_number, s.serial_number, s.form_factor, s.ecc].filter((x: any) => !isBlank(x)).join(' · ')}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                {(!mem.slots || mem.slots.length === 0) && (
                  <p className="muted">Firmware/OS did not expose DIMM topology.</p>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {tab === 'GPU' && (
        <div className="grid">
          {!socPcie && (
            <div className="card">
              <h3 className="section-title">PCIe GPU slots</h3>
              {(hw?.pcie?.slots || []).length > 0 ? (
                <>
                  {hw?.pcie?.gpu_capable_total != null && (
                    <p>GPU-capable slots: {hw.pcie.gpu_capable_total} · occupied {hw.pcie.gpu_capable_occupied} · free {hw.pcie.gpu_capable_free}</p>
                  )}
                  <table>
                    <thead><tr><th>Slot</th><th>Type</th><th>Width</th><th>Usage</th><th>GPU-capable</th><th>Device</th></tr></thead>
                    <tbody>
                      {hw.pcie.slots.map((s: any) => (
                        <tr key={s.slot_designation}>
                          <td>{s.slot_designation}</td>
                          <td>{s.slot_type}</td>
                          <td>{s.width}</td>
                          <td>{s.current_usage}</td>
                          <td>{s.is_gpu_capable == null ? '—' : s.is_gpu_capable ? 'Yes' : 'No'}</td>
                          <td>{s.attached_device}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              ) : (
                <p className="muted">PCIe slot map was not exposed by firmware.</p>
              )}
            </div>
          )}
          <div className="gpu-grid">
            {(hw?.gpus || []).map((g: any) => {
              const soc = isSocGpu(g)
              const extra = g.extra || {}
              const rails = extra.power_rails || {}
              const railText = Object.entries(rails)
                .map(([name, watts]) => `${name} ${Number(watts).toFixed(2)} W`)
                .join(' · ')
              const unified = extra.unified_ram_bytes || (soc ? g.vram_bytes : null)
              const unifiedUsed = extra.unified_ram_used_bytes
              return (
                <div className="card" key={g.index}>
                  <h3 style={{ marginTop: 0 }}>GPU {g.index} · {g.model}</h3>
                  <div className="muted">{[g.vendor, soc ? 'SoC (nvgpu)' : g.slot_designation].filter((x) => !isBlank(x)).join(' · ')}</div>
                  <Show label="Temperature" value={g.temperature_c != null ? `${g.temperature_c} °C` : null} />
                  <Show label="Utilization" value={g.utilization_pct != null ? `${g.utilization_pct}%` : null} />
                  <Meter value={g.utilization_pct} />
                  {soc ? (
                    <Show
                      label="Memory"
                      value={
                        unified
                          ? `Unified with system RAM ${bytes(unified)}${unifiedUsed != null ? ` · used ${bytes(unifiedUsed)}` : ''}`
                          : null
                      }
                    />
                  ) : (
                    <Show label="VRAM" value={bytes(g.vram_bytes)} />
                  )}
                  <Show label="GPU power" value={g.power_w != null ? `${g.power_w} W` : null} />
                  <Show label="Board power" value={extra.board_power_w != null ? `${extra.board_power_w} W` : null} supported={soc} />
                  {soc && railText ? <p className="muted">{railText}</p> : null}
                  <Show label="Graphics clock" value={g.graphics_clock_mhz != null ? `${g.graphics_clock_mhz} MHz` : null} />
                  <Show label={soc ? 'EMC / memory clock' : 'Memory clock'} value={g.memory_clock_mhz != null ? `${g.memory_clock_mhz} MHz` : null} />
                  <Show label="Driver" value={g.driver_version} />
                  <Show label="L4T" value={extra.l4t_version} supported={Boolean(soc && extra.l4t_version && extra.l4t_version !== g.driver_version)} />
                  <Show label="PCI" value={g.pci_bus} supported={!soc} />
                  <Show label="Serial" value={g.serial_number} supported={!soc} />
                </div>
              )
            })}
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
                  <td>{isBlank(d.smart_status) ? '—' : d.smart_status}</td>
                  <td>{d.temperature_c != null ? `${d.temperature_c}°C` : '—'}</td>
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
          <div className="section-head">
            <h3 className="section-title">Hardware history</h3>
            {canManage && (
              <button className="btn danger" type="button" disabled={busy === 'history'} onClick={() => clearKind('history')}>
                Clear history
              </button>
            )}
          </div>
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
          <div className="section-head">
            <h3 className="section-title">Events</h3>
            {canManage && (
              <button className="btn danger" type="button" disabled={busy === 'events'} onClick={() => clearKind('events')}>
                Clear events
              </button>
            )}
          </div>
          {events.map((e) => (
            <div key={e.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--line)' }}>
              <span className={`badge ${e.severity}`}>{e.event_type}</span> {e.summary}
              <div className="muted">{ago(e.created_at)}</div>
            </div>
          ))}
          {events.length === 0 && <p className="muted">No events for this machine.</p>}
        </div>
      )}

      {tab === 'Logs' && (
        <div className="card">
          <div className="section-head">
            <h3 className="section-title">Logs</h3>
            {canManage && (
              <button className="btn danger" type="button" disabled={busy === 'logs'} onClick={() => clearKind('logs')}>
                Clear logs
              </button>
            )}
          </div>
          <div className="toolbar">
            {['ALL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'CRITICAL'].map((lvl) => (
              <button
                key={lvl}
                type="button"
                className={`btn ${logLevel === lvl ? '' : 'secondary'}`}
                onClick={() => setLogLevel(lvl)}
              >
                {lvl === 'ALL' ? 'All logs' : lvl.charAt(0) + lvl.slice(1).toLowerCase()}
              </button>
            ))}
            <input
              placeholder="Search log message"
              value={logQuery}
              onChange={(e) => setLogQuery(e.target.value)}
            />
          </div>
          {logs.map((l) => {
            const details = l.details && typeof l.details === 'object' ? l.details : {}
            const extra = Object.keys(details).filter((k) => k !== 'source')
            return (
              <div key={l.id} className="log-line">
                <span className={`badge ${l.level}`}>{l.level}</span>{' '}
                <span className="muted">{l.source || 'agent'}</span>{' '}
                <span className="muted">{ago(l.created_at)}</span>
                <div className="msg">{l.message}</div>
                {extra.length > 0 && <pre className="muted">{JSON.stringify(details, null, 2)}</pre>}
              </div>
            )
          })}
          {logs.length === 0 && <p className="muted">No agent logs for this filter yet. After the agent heartbeats they appear here.</p>}
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
  const has = data.some((row) => row[dataKey] != null)
  if (!has) return null
  return (
    <div style={{ height: 220 }}>
      <h3 className="section-title">{title}</h3>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data}>
          <XAxis dataKey="t" hide />
          <YAxis width={40} />
          <Tooltip />
          <Line type="monotone" dataKey={dataKey} stroke="#3dbe9a" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
