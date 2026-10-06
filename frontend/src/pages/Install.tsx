import { useMemo, useState } from 'react'

function CopyBlock({ label, text }: { label: string; text: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div className="card install-cmd">
      <div className="section-head">
        <h3 className="section-title">{label}</h3>
        <button type="button" className="btn secondary" onClick={copy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="install-pre">{text}</pre>
    </div>
  )
}

export default function Install() {
  const base = useMemo(() => window.location.origin.replace(/\/$/, ''), [])

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
          <CopyBlock label="Download + install" text={linuxOne} />
          <CopyBlock label="Check status" text={linuxStatus} />
        </div>

        <div>
          <div className="topbar" style={{ marginBottom: 12 }}>
            <div>
              <h2 style={{ fontSize: 20 }}>Windows</h2>
              <p>Admin PowerShell. Needs Python 3.8+ on PATH.</p>
            </div>
          </div>
          <CopyBlock label="Install (Admin PowerShell)" text={winRun} />
          <CopyBlock label="If irm is blocked" text={winAlt} />
          <CopyBlock label="Check status" text={winStatus} />
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
