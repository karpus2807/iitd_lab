type Props = {
  page: number
  pageSize?: number
  total: number
  onChange: (page: number) => void
  disabled?: boolean
}

/** First / Prev / numbered / Next / Last — 25 items per page by default. */
export default function PageBar({ page, pageSize = 25, total, onChange, disabled }: Props) {
  const pages = Math.max(1, Math.ceil((total || 0) / pageSize))
  const safe = Math.min(Math.max(1, page), pages)
  if (total <= pageSize) {
    return (
      <div className="muted" style={{ padding: '10px 16px', fontSize: 13 }}>
        {total} item{total === 1 ? '' : 's'}
      </div>
    )
  }

  const windowSize = 5
  let start = Math.max(1, safe - Math.floor(windowSize / 2))
  let end = Math.min(pages, start + windowSize - 1)
  start = Math.max(1, end - windowSize + 1)
  const nums: number[] = []
  for (let i = start; i <= end; i++) nums.push(i)

  const go = (p: number) => {
    if (disabled) return
    onChange(Math.min(pages, Math.max(1, p)))
  }

  return (
    <div
      className="toolbar"
      style={{ padding: '10px 16px', gap: 6, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}
    >
      <span className="muted" style={{ fontSize: 13 }}>
        {(safe - 1) * pageSize + 1}–{Math.min(safe * pageSize, total)} of {total}
      </span>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
        <button className="btn secondary" type="button" disabled={disabled || safe <= 1} onClick={() => go(1)}>
          First
        </button>
        <button className="btn secondary" type="button" disabled={disabled || safe <= 1} onClick={() => go(safe - 1)}>
          Prev
        </button>
        {nums.map((n) => (
          <button
            key={n}
            className={n === safe ? 'btn' : 'btn secondary'}
            type="button"
            disabled={disabled}
            onClick={() => go(n)}
            style={{ minWidth: 36 }}
          >
            {n}
          </button>
        ))}
        <button className="btn secondary" type="button" disabled={disabled || safe >= pages} onClick={() => go(safe + 1)}>
          Next
        </button>
        <button className="btn secondary" type="button" disabled={disabled || safe >= pages} onClick={() => go(pages)}>
          Last
        </button>
      </div>
    </div>
  )
}

export const PAGE_SIZE = 25
