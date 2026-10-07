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
  const linuxStatus2 = 'sudo systemctl status labwatch-agent'
  const linuxUn1 = 'sudo systemctl disable --now labwatch-agent'
  const linuxUn2 = 'sudo rm -f /etc/systemd/system/labwatch-agent.service /usr/local/bin/labwatch-agent'
  const linuxUn3 = 'sudo systemctl daemon-reload'
  const linuxUn4 = 'sudo rm -rf /opt/labwatch-agent'
  const linuxUn5 = 'sudo rm -rf /etc/labwatch-agent /var/lib/labwatch-agent'

  const win1 = 'Remove-Item $env:TEMP\\labwatch-install.ps1 -ErrorAction SilentlyContinue'
  const win2 = `Invoke-WebRequest -Uri ${base}/install-agent.ps1 -OutFile $env:TEMP\\labwatch-install.ps1`
  const win3 = 'Get-Content $env:TEMP\\labwatch-install.ps1 -TotalCount 3'
  const win4 =
    'Select-String -Path $env:TEMP\\labwatch-install.ps1 -Pattern "ConvertTo-ObjectArray|agent-pack.tgz" | Select-Object -First 5'
  const win5 = 'powershell -ExecutionPolicy Bypass -File $env:TEMP\\labwatch-install.ps1'
  const winStatus = 'Get-ScheduledTask -TaskName LabWatchAgent'
  const winStatus2 = 'Get-ScheduledTaskInfo -TaskName LabWatchAgent'
  const winUn1 = 'Stop-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue'
  const winUn2 = 'Unregister-ScheduledTask -TaskName "LabWatchAgent" -Confirm:$false -ErrorAction SilentlyContinue'
  const winUn3 = 'Remove-Item -Recurse -Force "$env:ProgramFiles\\LabWatch Agent" -ErrorAction SilentlyContinue'
  const winUn4 = 'Remove-Item -Recurse -Force "$env:ProgramData\\LabWatch" -ErrorAction SilentlyContinue'

  const winGh2 = `Invoke-WebRequest -Uri ${GH_LATEST_PS1} -OutFile $env:TEMP\\labwatch-install.ps1`
  const winGh5 =
    'powershell -ExecutionPolicy Bypass -File $env:TEMP\\labwatch-install.ps1 -FromGitHub'

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Install agent</h2>
          <p>Copy one command at a time. Use a LabWatch admin or operator login (not SSH).</p>
        </div>
      </div>

      {toast && (
        <div className={`install-toast ${toast.kind}`} role="status" aria-live="polite">
          {toast.message}
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <h3 className="section-title">Before you start</h3>
        <ul className="install-list">
          <li>
            LabWatch server: <code className="mono">{base}</code> — main install path for lab PCs (works with campus
            proxy).
          </li>
          <li>
            <strong>Windows primary:</strong> download installer + agent pack from this server. Commands stay the same
            when versions change.
          </li>
          <li>
            <strong>GitHub:</strong> optional only (no campus proxy / GitHub reachable). Always pulls the latest
            release.
          </li>
          <li>
            <strong>Linux and Windows:</strong> username → password → machine ID → lab number. Token is automatic.
          </li>
          <li>Do not paste prompts like <code>PS C:\…&gt;</code> or <code>&gt;&gt;</code>.</li>
        </ul>
      </div>

      <div className="split install-split">
        <div>
          <div className="topbar" style={{ marginBottom: 12 }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Linux — install</h2>
              <p>Root / sudo. Needs curl and Python 3.8+.</p>
            </div>
          </div>
          <CopyBlock label="1) Download" text={linuxDownload} onResult={onResult} />
          <CopyBlock
            label="2) Install"
            text={linuxRun}
            onResult={onResult}
            hint="Asks username, password, machine ID, then lab number."
          />
          <CopyBlock label="3) Status" text={linuxStatus} onResult={onResult} />
          <CopyBlock label="4) Service status" text={linuxStatus2} onResult={onResult} />

          <div className="topbar" style={{ margin: '28px 0 12px' }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Linux — uninstall</h2>
              <p>Run in order. Then remove the host on the website if needed.</p>
            </div>
          </div>
          <CopyBlock label="U1) Stop service" text={linuxUn1} onResult={onResult} />
          <CopyBlock label="U2) Remove unit + binary" text={linuxUn2} onResult={onResult} />
          <CopyBlock label="U3) Reload systemd" text={linuxUn3} onResult={onResult} />
          <CopyBlock label="U4) Remove agent files" text={linuxUn4} onResult={onResult} />
          <CopyBlock
            label="U5) Wipe config + state (optional)"
            text={linuxUn5}
            onResult={onResult}
            hint="Skip this if you want the next install to keep the same machine ID and lab."
          />
        </div>

        <div>
          <div className="topbar" style={{ marginBottom: 12 }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Windows — install (primary: LabWatch server)</h2>
              <p>Admin PowerShell. Python 3.8+ from python.org (Add to PATH). Best for lab PCs with campus proxy.</p>
            </div>
          </div>
          <CopyBlock label="1) Delete old installer" text={win1} onResult={onResult} />
          <CopyBlock
            label="2) Download from LabWatch server"
            text={win2}
            onResult={onResult}
            hint="Uses this portal host. Agent pack also comes from the same server."
          />
          <CopyBlock
            label="3) Preview file"
            text={win3}
            onResult={onResult}
            hint="Must say ASCII-only (plain - arrows, not â€)."
          />
          <CopyBlock
            label="4) Confirm script"
            text={win4}
            onResult={onResult}
            hint="Must show ConvertTo-ObjectArray and agent-pack.tgz. If not, repeat steps 1–2."
          />
          <CopyBlock
            label="5) Run installer"
            text={win5}
            onResult={onResult}
            hint="Then enter username, password, machine ID, and lab number (1, 2, 3…)."
          />
          <CopyBlock label="6) Task status" text={winStatus} onResult={onResult} />
          <CopyBlock label="7) Last run result" text={winStatus2} onResult={onResult} />

          <div className="topbar" style={{ margin: '28px 0 12px' }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Windows — optional GitHub path</h2>
              <p>Only if GitHub works on that PC. Always downloads the latest release (no version number in the URL).</p>
            </div>
          </div>
          <CopyBlock label="G1) Delete old installer" text={win1} onResult={onResult} />
          <CopyBlock label="G2) Download latest from GitHub" text={winGh2} onResult={onResult} />
          <CopyBlock label="G3) Preview file" text={win3} onResult={onResult} />
          <CopyBlock
            label="G4) Run with -FromGitHub"
            text={winGh5}
            onResult={onResult}
            hint="Pulls the latest agent zip from GitHub; login still goes to the LabWatch server."
          />

          <div className="topbar" style={{ margin: '28px 0 12px' }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Windows — uninstall</h2>
              <p>Admin PowerShell. One step at a time.</p>
            </div>
          </div>
          <CopyBlock label="U1) Stop task" text={winUn1} onResult={onResult} />
          <CopyBlock label="U2) Remove scheduled task" text={winUn2} onResult={onResult} />
          <CopyBlock label="U3) Remove Program Files" text={winUn3} onResult={onResult} />
          <CopyBlock
            label="U4) Wipe ProgramData (optional)"
            text={winUn4}
            onResult={onResult}
            hint="Skip this if you want the next install to keep the same machine ID and lab."
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
