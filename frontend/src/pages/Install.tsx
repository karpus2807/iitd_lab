import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'

async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      /* fall through */
    }
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.setAttribute('readonly', '')
  ta.style.position = 'fixed'
  ta.style.top = '0'
  ta.style.left = '0'
  ta.style.width = '1px'
  ta.style.height = '1px'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.focus()
  ta.select()
  ta.setSelectionRange(0, text.length)
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  document.body.removeChild(ta)
  return ok
}

function CopyBlock({
  label,
  text,
  onResult,
}: {
  label: string
  text: string
  onResult: (ok: boolean, label: string) => void
}) {
  const [busy, setBusy] = useState(false)
  async function copy() {
    setBusy(true)
    const ok = await copyText(text)
    setBusy(false)
    onResult(ok, label)
  }
  return (
    <div className="card install-cmd">
      <div className="section-head">
        <h3 className="section-title">{label}</h3>
        <button type="button" className="btn secondary" disabled={busy || !text} onClick={copy}>
          {busy ? 'Copying…' : 'Copy'}
        </button>
      </div>
      <pre className="install-pre">{text}</pre>
    </div>
  )
}

type Toast = { kind: 'ok' | 'err'; message: string }

type InstallInfo = {
  server_url: string
  server_version: string
  agent_version: string
  github_repo: string
  github_install_ps1: string
  requirements: {
    linux_os: string
    windows_os: string
    host_python: string
    agent_python: string
  }
  runtimes: Record<string, boolean>
  features: string[]
  existing_agents: {
    need_update_for_displays: boolean
    display_monitor_min: string
    safe_update_min: string
    remote_update_min: string
    linux_update_fix_min?: string
    keep_awake_min?: string
    summary: string
  }
  notes: string[]
  commands: {
    linux: Record<string, string>
    windows: Record<string, string>
  }
}

function fallbackInfo(base: string): InstallInfo {
  const github = 'https://github.com/karpus2807/iitd_lab/releases/latest/download/install-agent.ps1'
  return {
    server_url: base,
    server_version: '—',
    agent_version: '—',
    github_repo: 'karpus2807/iitd_lab',
    github_install_ps1: github,
    requirements: {
      linux_os: 'Ubuntu 16.04+',
      windows_os: 'Windows 10 / 11',
      host_python: 'Any — left unchanged',
      agent_python: 'Bundled CPython 3.12 when needed',
    },
    runtimes: {},
    features: [],
    existing_agents: {
      need_update_for_displays: true,
      display_monitor_min: '1.2.6',
      safe_update_min: '1.2.3',
      remote_update_min: '1.1.40',
      summary: 'Use Admin → Agents to push the current pack when hosts are online.',
    },
    notes: ['Could not load live install info — commands below still use this server URL.'],
    commands: {
      linux: {
        download: `curl -fsSL --noproxy '*' ${base}/install-agent.sh -o /tmp/labwatch-install.sh && head -1 /tmp/labwatch-install.sh | grep -q '^#!'`,
        install: 'sudo bash /tmp/labwatch-install.sh',
        status: 'labwatch-agent status',
        fix_venv: 'sudo rm -rf /opt/labwatch-agent/venv /opt/labwatch-agent/python',
        restart: 'sudo systemctl start labwatch-agent; systemctl is-active labwatch-agent',
        force_update: [
          'sudo systemctl stop labwatch-agent',
          `curl -fsSL --noproxy '*' ${base}/agent-pack.tgz -o /tmp/labwatch-agent-pack.tgz`,
          'rm -rf /tmp/labwatch-pack && mkdir -p /tmp/labwatch-pack',
          'tar -xzf /tmp/labwatch-agent-pack.tgz -C /tmp/labwatch-pack',
          'sudo rm -rf /opt/labwatch-agent/labwatch_agent /opt/labwatch-agent/labwatch_agent.next /opt/labwatch-agent/labwatch_agent.prev',
          'sudo cp -a /tmp/labwatch-pack/labwatch_agent /opt/labwatch-agent/',
          'sudo systemctl start labwatch-agent',
          'sleep 1',
          'labwatch-agent version',
          'systemctl is-active labwatch-agent',
        ].join('\n'),
        uninstall_stop: 'sudo systemctl disable --now labwatch-agent',
        uninstall_unit:
          'sudo rm -f /etc/systemd/system/labwatch-agent.service /usr/local/bin/labwatch-agent && sudo systemctl daemon-reload',
        uninstall_wipe: 'sudo rm -rf /opt/labwatch-agent /etc/labwatch-agent /var/lib/labwatch-agent',
      },
      windows: {
        clear_installer: 'Remove-Item $env:TEMP\\labwatch-install.ps1 -ErrorAction SilentlyContinue',
        download: `Invoke-WebRequest -Uri ${base}/install-agent.ps1 -OutFile $env:TEMP\\labwatch-install.ps1`,
        install: 'powershell -ExecutionPolicy Bypass -File $env:TEMP\\labwatch-install.ps1',
        status: 'Get-ScheduledTask -TaskName LabWatchAgent',
        fix_venv:
          'Remove-Item -Recurse -Force "$env:ProgramFiles\\LabWatch Agent\\venv","$env:ProgramFiles\\LabWatch Agent\\python" -ErrorAction SilentlyContinue',
        restart_task:
          'Start-ScheduledTask -TaskName "LabWatchAgent"; Get-ScheduledTask -TaskName "LabWatchAgent" | Select-Object TaskName, State',
        github_download: `Invoke-WebRequest -Uri ${github} -OutFile $env:TEMP\\labwatch-install.ps1`,
        github_install: 'powershell -ExecutionPolicy Bypass -File $env:TEMP\\labwatch-install.ps1 -FromGitHub',
        uninstall_task:
          'Stop-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName "LabWatchAgent" -Confirm:$false -ErrorAction SilentlyContinue',
        uninstall_wipe:
          'Remove-Item -Recurse -Force "$env:ProgramFiles\\LabWatch Agent","$env:ProgramData\\LabWatch" -ErrorAction SilentlyContinue',
      },
    },
  }
}

function Section({ title }: { title: string }) {
  return (
    <div className="topbar" style={{ margin: '24px 0 10px' }}>
      <div>
        <h2 style={{ fontSize: 18, margin: 0 }}>{title}</h2>
      </div>
    </div>
  )
}

export default function Install() {
  const pageBase = useMemo(() => window.location.origin.replace(/\/$/, ''), [])
  const [info, setInfo] = useState<InstallInfo | null>(null)
  const [loadErr, setLoadErr] = useState('')
  const [toast, setToast] = useState<Toast | null>(null)

  useEffect(() => {
    let cancelled = false
    api<InstallInfo>('/api/install/info')
      .then((data) => {
        if (!cancelled) setInfo(data)
      })
      .catch(() => {
        if (!cancelled) {
          setLoadErr('Live install info unavailable — using this page URL for commands.')
          setInfo(fallbackInfo(pageBase))
        }
      })
    return () => {
      cancelled = true
    }
  }, [pageBase])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 2500)
    return () => window.clearTimeout(t)
  }, [toast])

  function onResult(ok: boolean, label: string) {
    if (ok) setToast({ kind: 'ok', message: `Copied “${label}”` })
    else setToast({ kind: 'err', message: 'Copy failed — select the command and Ctrl+C' })
  }

  const data = info || fallbackInfo(pageBase)
  const base = data.server_url || pageBase
  const L = data.commands.linux
  const W = data.commands.windows
  const ea = data.existing_agents

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Install agent</h2>
          <p>
            Pack <code className="mono">{data.agent_version || '—'}</code>
            {data.server_version && data.server_version !== '—' ? (
              <>
                {' '}
                · server <code className="mono">{data.server_version}</code>
              </>
            ) : null}
            {' '}
            · <code className="mono">{base}</code>
          </p>
        </div>
      </div>

      {toast && (
        <div className={`install-toast ${toast.kind}`} role="status" aria-live="polite">
          {toast.message}
        </div>
      )}
      {loadErr ? <p className="muted">{loadErr}</p> : null}

      <div className="card" style={{ marginBottom: 16 }}>
        <ul className="install-list" style={{ margin: 0 }}>
          <li>
            {data.requirements.linux_os} · {data.requirements.windows_os} · host Python unchanged ·{' '}
            {data.requirements.agent_python}
          </li>
          <li>
            Login: LabWatch admin/operator → machine ID → lab. Do not paste <code className="mono">PS&gt;</code> /{' '}
            <code className="mono">&gt;&gt;</code>.
          </li>
          <li>
            Existing agents: Admin → Agents (online). Displays ≥{ea.display_monitor_min}, remote update ≥
            {ea.remote_update_min}
            {ea.linux_update_fix_min ? `, Linux update fix ≥${ea.linux_update_fix_min}` : ''}.
          </li>
          {data.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </div>

      <div className="split install-split">
        <div>
          <Section title="Linux — install" />
          <CopyBlock label="1) Download" text={L.download} onResult={onResult} />
          <CopyBlock label="2) Install" text={L.install} onResult={onResult} />
          <CopyBlock label="3) Status" text={L.status} onResult={onResult} />

          <Section title="Linux — fix / offline" />
          <CopyBlock label="Clear broken venv" text={L.fix_venv} onResult={onResult} />
          {L.restart ? <CopyBlock label="Start service" text={L.restart} onResult={onResult} /> : null}
          {L.force_update ? (
            <CopyBlock label="Force-swap pack + start" text={L.force_update} onResult={onResult} />
          ) : null}
          <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>
            Force-swap needs sudo on rm/cp. After clearing venv: run Download + Install again.
          </p>

          <Section title="Linux — uninstall" />
          <CopyBlock label="Stop service" text={L.uninstall_stop} onResult={onResult} />
          <CopyBlock label="Remove unit" text={L.uninstall_unit} onResult={onResult} />
          <CopyBlock label="Wipe data (optional)" text={L.uninstall_wipe} onResult={onResult} />
        </div>

        <div>
          <Section title="Windows — install" />
          <CopyBlock label="1) Clear old script" text={W.clear_installer} onResult={onResult} />
          <CopyBlock label="2) Download" text={W.download} onResult={onResult} />
          <CopyBlock label="3) Install" text={W.install} onResult={onResult} />
          <CopyBlock label="4) Status" text={W.status} onResult={onResult} />

          <Section title="Windows — fix / offline" />
          <CopyBlock label="Clear broken venv" text={W.fix_venv} onResult={onResult} />
          <CopyBlock label="Restart task" text={W.restart_task} onResult={onResult} />
          <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>
            After clearing venv: run Clear + Download + Install again.
          </p>

          <Section title="Windows — GitHub (optional)" />
          <CopyBlock label="Download release" text={W.github_download} onResult={onResult} />
          <CopyBlock label="Install -FromGitHub" text={W.github_install} onResult={onResult} />

          <Section title="Windows — uninstall" />
          <CopyBlock label="Remove task" text={W.uninstall_task} onResult={onResult} />
          <CopyBlock label="Wipe data (optional)" text={W.uninstall_wipe} onResult={onResult} />
        </div>
      </div>

      <p className="muted" style={{ marginTop: 16, fontSize: 13 }}>
        After install → Machines. After uninstall → machine page → Remove from LabWatch.
      </p>
    </>
  )
}
