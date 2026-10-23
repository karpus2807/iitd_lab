import { useEffect, useMemo, useState } from 'react'

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
  hint,
}: {
  label: string
  text: string
  onResult: (ok: boolean, label: string) => void
  hint?: string
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
        <button type="button" className="btn secondary" disabled={busy} onClick={copy}>
          {busy ? 'Copying…' : 'Copy'}
        </button>
      </div>
      {hint ? <p className="muted install-hint">{hint}</p> : null}
      <pre className="install-pre">{text}</pre>
    </div>
  )
}

type Toast = { kind: 'ok' | 'err'; message: string }

const GH_LATEST_PS1 =
  'https://github.com/karpus2807/iitd_lab/releases/latest/download/install-agent.ps1'

export default function Install() {
  const base = useMemo(() => window.location.origin.replace(/\/$/, ''), [])
  const [toast, setToast] = useState<Toast | null>(null)

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 2500)
    return () => window.clearTimeout(t)
  }, [toast])

  function onResult(ok: boolean, label: string) {
    if (ok) {
      setToast({ kind: 'ok', message: `Copied “${label}” to clipboard` })
    } else {
      setToast({ kind: 'err', message: 'Could not copy — select the command and press Ctrl+C' })
    }
  }

  const linuxDownload = `curl -fsSL ${base}/install-agent.sh -o /tmp/labwatch-install.sh`
  const linuxRun = 'sudo bash /tmp/labwatch-install.sh'
  const linuxStatus = 'labwatch-agent status'
  const linuxUn1 = 'sudo systemctl disable --now labwatch-agent'
  const linuxUn2 =
    'sudo rm -f /etc/systemd/system/labwatch-agent.service /usr/local/bin/labwatch-agent && sudo systemctl daemon-reload'
  const linuxUn3 = 'sudo rm -rf /opt/labwatch-agent /etc/labwatch-agent /var/lib/labwatch-agent'

  const win1 = 'Remove-Item $env:TEMP\\labwatch-install.ps1 -ErrorAction SilentlyContinue'
  const win2 = `Invoke-WebRequest -Uri ${base}/install-agent.ps1 -OutFile $env:TEMP\\labwatch-install.ps1`
  const win3 = 'powershell -ExecutionPolicy Bypass -File $env:TEMP\\labwatch-install.ps1'
  const winStatus = 'Get-ScheduledTask -TaskName LabWatchAgent'
  const winUn1 =
    'Stop-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName "LabWatchAgent" -Confirm:$false -ErrorAction SilentlyContinue'
  const winUn2 =
    'Remove-Item -Recurse -Force "$env:ProgramFiles\\LabWatch Agent","$env:ProgramData\\LabWatch" -ErrorAction SilentlyContinue'

  const winGh2 = `Invoke-WebRequest -Uri ${GH_LATEST_PS1} -OutFile $env:TEMP\\labwatch-install.ps1`
  const winGh3 =
    'powershell -ExecutionPolicy Bypass -File $env:TEMP\\labwatch-install.ps1 -FromGitHub'

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Install agent</h2>
          <p>Install the latest agent from this LabWatch server. Copy one command at a time.</p>
        </div>
      </div>

      {toast && (
        <div className={`install-toast ${toast.kind}`} role="status" aria-live="polite">
          {toast.message}
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <h3 className="section-title">Quick notes</h3>
        <ul className="install-list">
          <li>
            Server: <code className="mono">{base}</code> — latest agent pack + pip wheels (no version to type).
          </li>
          <li>
            Dependencies install from this server only — lab PCs do not need campus proxy / PyPI for agent packages.
          </li>
          <li>Login with LabWatch admin/operator (not SSH). Prompts: username → password → machine ID → lab number.</li>
          <li>Windows: Python 3.8+ from python.org with “Add to PATH”. Linux: curl + Python 3.8+ + sudo.</li>
          <li>Do not paste prompts like <code>PS C:\…&gt;</code> or <code>&gt;&gt;</code>.</li>
        </ul>
      </div>

      <div className="split install-split">
        <div>
          <div className="topbar" style={{ marginBottom: 12 }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Linux — latest install</h2>
              <p>Root / sudo. Downloads current agent from this server.</p>
            </div>
          </div>
          <CopyBlock label="1) Download" text={linuxDownload} onResult={onResult} />
          <CopyBlock
            label="2) Install"
            text={linuxRun}
            onResult={onResult}
            hint="Enter username, password, machine ID, then lab number."
          />
          <CopyBlock label="3) Status" text={linuxStatus} onResult={onResult} />

          <div className="topbar" style={{ margin: '28px 0 12px' }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Linux — uninstall</h2>
            </div>
          </div>
          <CopyBlock label="U1) Stop service" text={linuxUn1} onResult={onResult} />
          <CopyBlock label="U2) Remove unit + binary" text={linuxUn2} onResult={onResult} />
          <CopyBlock
            label="U3) Wipe files (optional)"
            text={linuxUn3}
            onResult={onResult}
            hint="Skip if the next install should keep the same machine ID and lab."
          />
        </div>

        <div>
          <div className="topbar" style={{ marginBottom: 12 }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Windows — latest install</h2>
              <p>Admin PowerShell. Primary path for lab PCs (campus proxy OK).</p>
            </div>
          </div>
          <CopyBlock label="1) Clear old installer" text={win1} onResult={onResult} />
          <CopyBlock
            label="2) Download latest from server"
            text={win2}
            onResult={onResult}
            hint="Installer + agent pack come from this LabWatch host."
          />
          <CopyBlock
            label="3) Run installer"
            text={win3}
            onResult={onResult}
            hint="Then enter username, password, machine ID, and lab number."
          />
          <CopyBlock label="4) Task status" text={winStatus} onResult={onResult} />

          <div className="topbar" style={{ margin: '28px 0 12px' }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Windows — GitHub latest (optional)</h2>
              <p>Only if GitHub works on that PC. Same enroll flow; agent zip from latest release.</p>
            </div>
          </div>
          <CopyBlock label="G1) Clear old installer" text={win1} onResult={onResult} />
          <CopyBlock label="G2) Download latest release" text={winGh2} onResult={onResult} />
          <CopyBlock
            label="G3) Run with -FromGitHub"
            text={winGh3}
            onResult={onResult}
            hint="Always pulls releases/latest — no version number in the URL."
          />

          <div className="topbar" style={{ margin: '28px 0 12px' }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Windows — uninstall</h2>
            </div>
          </div>
          <CopyBlock label="U1) Stop + remove task" text={winUn1} onResult={onResult} />
          <CopyBlock
            label="U2) Wipe Program Files + ProgramData (optional)"
            text={winUn2}
            onResult={onResult}
            hint="Skip ProgramData wipe if the next install should keep machine ID and lab."
          />
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3 className="section-title">After install / uninstall</h3>
        <p className="muted" style={{ margin: 0 }}>
          After install, open <strong>Machines</strong> — the PC should appear with your machine ID. After uninstall,
          open the machine page and click <strong>Remove from LabWatch</strong> so it leaves the fleet list.
        </p>
      </div>
    </>
  )
}
