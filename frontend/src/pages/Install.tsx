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

const WIN_TAG = 'v1.1.32'
const WIN_SCRIPT = `https://github.com/karpus2807/iitd_lab/releases/download/${WIN_TAG}/install-agent.ps1`

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

  const win1 = 'Remove-Item $env:TEMP\\labwatch-install.ps1 -ErrorAction SilentlyContinue'
  const win2 = `Invoke-WebRequest -Uri ${WIN_SCRIPT} -OutFile $env:TEMP\\labwatch-install.ps1`
  const win3 = 'Get-Content $env:TEMP\\labwatch-install.ps1 -TotalCount 3'
  const win4 = 'Select-String -Path $env:TEMP\\labwatch-install.ps1 -Pattern "ConvertTo-ObjectArray|v1.1.32" | Select-Object -First 5'
  const win5 = 'powershell -ExecutionPolicy Bypass -File $env:TEMP\\labwatch-install.ps1'

  const linuxStatus = 'labwatch-agent status'
  const linuxStatus2 = 'sudo systemctl status labwatch-agent'
  const winStatus = 'Get-ScheduledTask -TaskName LabWatchAgent'
  const winStatus2 = 'Get-ScheduledTaskInfo -TaskName LabWatchAgent'

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
          <li>LabWatch server: <code className="mono">{base}</code> (login / enroll only).</li>
          <li><strong>Windows:</strong> download installer from <strong>GitHub</strong> — do not paste prompts like <code>PS C:\…&gt;</code> or <code>&gt;&gt;</code>.</li>
          <li><strong>Linux and Windows:</strong> username → password → machine ID → lab number. Token is automatic.</li>
          <li>Password typing is invisible. Re-run: press Enter to keep machine ID and lab.</li>
          <li>Only <strong>ADMIN</strong> or <strong>OPERATOR</strong> can enroll. Same login works on many PCs.</li>
        </ul>
      </div>

      <div className="split install-split">
        <div>
          <div className="topbar" style={{ marginBottom: 12 }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Linux</h2>
              <p>Root / sudo. Needs curl and Python 3.8+. Run step 1, then step 2.</p>
            </div>
          </div>
          <CopyBlock label="1) Download" text={linuxDownload} onResult={onResult} />
          <CopyBlock label="2) Install" text={linuxRun} onResult={onResult} hint="Asks username, password, machine ID, then lab number." />
          <CopyBlock label="3) Status" text={linuxStatus} onResult={onResult} />
          <CopyBlock label="4) Service status" text={linuxStatus2} onResult={onResult} />
        </div>

        <div>
          <div className="topbar" style={{ marginBottom: 12 }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Windows 10 / 11</h2>
              <p>Admin PowerShell. Python 3.8+ from python.org (Add to PATH). One step at a time.</p>
            </div>
          </div>
          <CopyBlock label="1) Delete old installer" text={win1} onResult={onResult} />
          <CopyBlock
            label={`2) Download from GitHub (${WIN_TAG})`}
            text={win2}
            onResult={onResult}
            hint="Do not use the hobbit /install-agent.ps1 URL for Windows."
          />
          <CopyBlock
            label="3) Preview file"
            text={win3}
            onResult={onResult}
            hint="Must say ASCII-only and same flow as Linux (plain - arrows, not â€)."
          />
          <CopyBlock
            label="4) Confirm version"
            text={win4}
            onResult={onResult}
            hint="Must show ConvertTo-ObjectArray and v1.1.32. If not, repeat steps 1–2."
          />
          <CopyBlock
            label="5) Run installer"
            text={win5}
            onResult={onResult}
            hint="Then enter username, password, machine ID, and lab number (1, 2, 3…)."
          />
          <CopyBlock label="6) Task status" text={winStatus} onResult={onResult} />
          <CopyBlock label="7) Last run result" text={winStatus2} onResult={onResult} />
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3 className="section-title">After install</h3>
        <p className="muted" style={{ margin: 0 }}>
          Open <strong>Machines</strong> — the PC should appear with your machine ID.
          Remove a host from Machines if you wipe the agent on that PC.
        </p>
      </div>
    </>
  )
}
