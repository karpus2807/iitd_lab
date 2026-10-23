import { useEffect, useRef } from 'react'

/** Shared progress + live log panel for any long-running server job. */
export type ProgressJob = {
  active?: boolean
  label?: string
  message?: string
  state?: string
  /** 0–100; omit/null → indeterminate while active */
  progress?: number | null
  step?: string
  log?: string
  error?: boolean
}

type Props = {
  job: ProgressJob
  /** Show even when idle if there is a finished log/message */
  showWhenIdle?: boolean
  className?: string
}

function clampPercent(n: number | null | undefined): number | null {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return null
  return Math.max(0, Math.min(100, Math.round(Number(n))))
}

export default function ProgressPanel({ job, showWhenIdle = false, className = '' }: Props) {
  const logRef = useRef<HTMLPreElement>(null)
  const pct = clampPercent(job.progress)
  const active = Boolean(job.active)
  const failed = Boolean(job.error) || job.state === 'error'
  const done = job.state === 'ok' || (pct === 100 && !failed)
  const visible = active || showWhenIdle || Boolean(job.log) || Boolean(job.message && job.state && job.state !== 'idle')

  useEffect(() => {
    const el = logRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [job.log])

  if (!visible) return null

  const barWidth = pct !== null ? `${pct}%` : active ? '35%' : '0%'
  const indeterminate = active && pct === null

  return (
    <div className={`progress-panel card ${className}`.trim()} data-state={failed ? 'error' : done ? 'ok' : active ? 'running' : 'idle'}>
      <div className="progress-panel-head">
        <div>
          <strong>{job.label || 'Progress'}</strong>
          {job.step ? <span className="muted progress-step"> · {job.step}</span> : null}
        </div>
        <div className="progress-pct mono">
          {failed ? 'failed' : done && !active ? '100%' : pct !== null ? `${pct}%` : active ? '…' : '—'}
        </div>
      </div>
      {job.message ? <p className="progress-msg">{job.message}</p> : null}
      <div className={`progress-track${indeterminate ? ' indeterminate' : ''}`} role="progressbar" aria-valuenow={pct ?? undefined} aria-valuemin={0} aria-valuemax={100}>
        <div className="progress-fill" style={{ width: barWidth }} />
      </div>
      {job.log ? (
        <pre className="progress-log" ref={logRef} tabIndex={0} aria-label="Live process log">
          {job.log}
        </pre>
      ) : active ? (
        <pre className="progress-log muted">Waiting for log output…</pre>
      ) : null}
    </div>
  )
}
