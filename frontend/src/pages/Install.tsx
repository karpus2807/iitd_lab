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
        <button type="button" className="btn secondary" disabled={busy} onClick={copy}>
          {busy ? 'Copying…' : 'Copy'}
        </button>
      </div>
      <pre className="install-pre">{text}</pre>
    </div>
  )
}

type Toast = { kind: 'ok' | 'err'; message: string }

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
  const linuxOne = `${linuxDownload}\n${linuxRun}`

  const winRun = `irm ${base}/install-agent.ps1 | iex`
  const winAlt = `Invoke-WebRequest -Uri ${base}/install-agent.ps1 -OutFile $env:TEMP\\labwatch-install.ps1\npowershell -ExecutionPolicy Bypass -File $env:TEMP\\labwatch-install.ps1`

  const linuxStatus = 'labwatch-agent status\nsudo systemctl status labwatch-agent'
  const winStatus = 'Get-ScheduledTask -TaskName LabWatchAgent'

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Install agent</h2>
          <p>Copy a command on the lab PC. Use an admin or operator LabWatch login (not SSH).</p>
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
          <li>Server URL for this portal: <code className="mono">{base}</code> (keep the port if shown).</li>
          <li>Login asks for LabWatch username/password, machine ID, then lab number.</li>
          <li>Password typing is invisible — type and press Enter.</li>
          <li>Re-run keeps machine ID and lab when you press Enter.</li>
          <li>Only <strong>ADMIN</strong> or <strong>OPERATOR</strong> can enroll a PC.</li>
        </ul>
      </div>

      <div className="split install-split">
        <div>
          <div className="topbar" style={{ marginBottom: 12 }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Linux</h2>
              <p>Root / sudo on the lab PC. Needs curl and Python 3.8+.</p>
            </div>
          </div>
          <CopyBlock label="Download + install" text={linuxOne} onResult={onResult} />
          <CopyBlock label="Check status" text={linuxStatus} onResult={onResult} />
        </div>

        <div>
          <div className="topbar" style={{ marginBottom: 12 }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Windows</h2>
              <p>Admin PowerShell. Needs Python 3.8+ on PATH.</p>
            </div>
          </div>
          <CopyBlock label="Install (Admin PowerShell)" text={winRun} onResult={onResult} />
          <CopyBlock label="If irm is blocked" text={winAlt} onResult={onResult} />
          <CopyBlock label="Check status" text={winStatus} onResult={onResult} />
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3 className="section-title">After install</h3>
        <p className="muted" style={{ margin: 0 }}>
          Open <strong>Machines</strong> — the PC should appear with your machine ID. Agent credentials stay after you change the website password.
          Remove a host from Machines if you wipe the agent on that PC.
        </p>
      </div>
    </>
  )
}
