import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ago, api, currentUser, downloadFile, getToken } from '../api'

type Lab = {
  id: string
  name: string
  room?: string
  building?: string
  protected?: boolean
}

type Scholar = {
  id: string
  lab_id: string
  lab_name: string
  lab_room: string
  full_name: string
  scholar_id: string
  group_name: string
  faculty: string
  system_required: boolean
  inventory_kind: string
  inventory_item_id: string | null
  inventory_label: string
  inventory_item_name: string
  email: string
  phone: string
  has_photo: boolean
  status: string
  notes?: string
  removed_at?: string | null
  removed_by?: string | null
  removal_remark?: string | null
}

type InvSuggest = {
  id: string
  ic_no: string
  item_name: string
  inventory_location: string
}

const EMPTY = {
  full_name: '',
  scholar_id: '',
  group_name: 'M.Tech',
  faculty: '',
  system_required: 'no',
  inventory_mode: 'listed' as 'listed' | 'non_list',
  inventory_item_id: '',
  inventory_label: '',
  inv_search: '',
  email: '',
  phone: '',
  notes: '',
  require_otp: false,
}

function ScholarPhoto({ id }: { id: string }) {
  const [src, setSrc] = useState('')
  useEffect(() => {
    let url = ''
    let cancelled = false
    ;(async () => {
      try {
        const token = getToken()
        const res = await fetch(`/api/scholars/${id}/photo`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
        if (!res.ok) return
        const blob = await res.blob()
        if (cancelled) return
        url = URL.createObjectURL(blob)
        setSrc(url)
      } catch {
        /* ignore */
      }
    })()
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [id])
  if (!src) return <span className="muted">…</span>
  return <img src={src} alt="" style={{ width: 40, height: 40, objectFit: 'cover', borderRadius: 6 }} />
}

export default function Scholars() {
  const role = currentUser()?.role
  const canEdit = role === 'ADMIN' || role === 'OPERATOR'
  const [tab, setTab] = useState<'active' | 'removed'>('active')
  const [labs, setLabs] = useState<Lab[]>([])
  const [labId, setLabId] = useState('')
  const [rows, setRows] = useState<Scholar[]>([])
  const [total, setTotal] = useState(0)
  const [q, setQ] = useState('')
  const [filterGroup, setFilterGroup] = useState('')
  const [filterFaculty, setFilterFaculty] = useState('')
  const [groups, setGroups] = useState<string[]>([])
  const [faculties, setFaculties] = useState<string[]>([])
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [detail, setDetail] = useState<Scholar | null>(null)
  const [form, setForm] = useState({ ...EMPTY })
  const [enrollOpen, setEnrollOpen] = useState(false)
  const [removeOpen, setRemoveOpen] = useState(false)
  const [removeRemark, setRemoveRemark] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState('')
  const [suggestions, setSuggestions] = useState<InvSuggest[]>([])
  const [showSuggest, setShowSuggest] = useState(false)
  const [photoFile, setPhotoFile] = useState<File | null>(null)
  const [otpChallengeId, setOtpChallengeId] = useState('')
  const [otpEmail, setOtpEmail] = useState('')
  const [otpCode, setOtpCode] = useState('')
  const [otpMessage, setOtpMessage] = useState('')
  const photoRef = useRef<HTMLInputElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const suggestRef = useRef<HTMLDivElement>(null)

  const selectedLab = useMemo(() => labs.find((l) => l.id === labId) || null, [labs, labId])
  const selectedIds = useMemo(() => rows.filter((r) => selected[r.id]).map((r) => r.id), [rows, selected])
  const allSelected = rows.length > 0 && rows.every((r) => selected[r.id])
  const filtersActive = !!(filterGroup || filterFaculty || q)

  const loadLabs = useCallback(async () => {
    const data = await api<Lab[]>('/api/labs')
    const usable = (data || []).filter((l) => !l.protected && l.name.toLowerCase() !== 'unassigned')
    setLabs(usable)
  }, [])

  const loadFacets = useCallback(async () => {
    const qs = new URLSearchParams()
    qs.set('status', tab)
    if (labId) qs.set('lab_id', labId)
    const data = await api<{ groups: string[]; faculties: string[] }>(`/api/scholars/facets?${qs}`)
    setGroups(data.groups || [])
    setFaculties(data.faculties || [])
  }, [labId, tab])

  const load = useCallback(async () => {
    setErr('')
    try {
      const qs = new URLSearchParams()
      qs.set('status', tab)
      qs.set('limit', '2000')
      if (labId) qs.set('lab_id', labId)
      if (q.trim()) qs.set('q', q.trim())
      if (filterGroup) qs.set('group_name', filterGroup)
      if (filterFaculty) qs.set('faculty', filterFaculty)
      const data = await api<{ items: Scholar[]; total: number }>(`/api/scholars?${qs}`)
      setRows(data.items || [])
      setTotal(data.total || 0)
      setSelected((prev) => {
        const next: Record<string, boolean> = {}
        for (const r of data.items || []) if (prev[r.id]) next[r.id] = true
        return next
      })
      setDetail((prev) => {
        if (!prev) return null
        return (data.items || []).find((x) => x.id === prev.id) || null
      })
    } catch (e: any) {
      setErr(e?.message || 'Could not load scholars')
      setRows([])
      setTotal(0)
    }
  }, [tab, labId, q, filterGroup, filterFaculty])

  useEffect(() => {
    void loadLabs().catch((e) => setErr(e.message))
  }, [loadLabs])
  useEffect(() => {
    void loadFacets().catch(() => undefined)
  }, [loadFacets])
  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (form.system_required !== 'yes' || form.inventory_mode !== 'listed') {
      setSuggestions([])
      return
    }
    const needle = form.inv_search.trim()
    if (needle.length < 1) {
      setSuggestions([])
      return
    }
    const t = window.setTimeout(() => {
      api<InvSuggest[]>(`/api/inventory/suggest?q=${encodeURIComponent(needle)}&limit=15`)
        .then((rows) => {
          setSuggestions(rows || [])
          setShowSuggest(true)
        })
        .catch(() => setSuggestions([]))
    }, 200)
    return () => window.clearTimeout(t)
  }, [form.inv_search, form.system_required, form.inventory_mode])

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!suggestRef.current?.contains(e.target as Node)) setShowSuggest(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  function labLabel(l: Lab) {
    const room = (l.room || '').trim()
    return room ? `${l.name} · Room ${room}` : l.name
  }

  function toggleAll(checked: boolean) {
    setSelected((prev) => {
      const next = { ...prev }
      for (const r of rows) {
        if (checked) next[r.id] = true
        else delete next[r.id]
      }
      return next
    })
  }

  async function submitEnroll(e: FormEvent) {
    e.preventDefault()
    if (!canEdit || !labId) return
    setBusy(true)
    setErr('')
    setNotice('')
    try {
      const fd = new FormData()
      fd.append('lab_id', labId)
      fd.append('full_name', form.full_name.trim())
      fd.append('scholar_id', form.scholar_id.trim())
      fd.append('group_name', form.group_name.trim())
      fd.append('faculty', form.faculty.trim())
      fd.append('email', form.email.trim())
      fd.append('phone', form.phone.trim())
      fd.append('notes', form.notes.trim())
      const sysYes = form.system_required === 'yes'
      fd.append('system_required', sysYes ? 'true' : 'false')
      if (sysYes) {
        if (form.inventory_mode === 'listed') {
          if (!form.inventory_item_id) throw new Error('Choose an inventory item from search results')
          fd.append('inventory_kind', 'listed')
          fd.append('inventory_item_id', form.inventory_item_id)
          fd.append('inventory_label', form.inventory_label)
        } else {
          const label = form.inventory_label.trim() || form.inv_search.trim()
          if (!label) throw new Error('Type a non-list inventory label / IC No.')
          fd.append('inventory_kind', 'non_list')
          fd.append('inventory_label', label)
        }
      } else {
        fd.append('inventory_kind', 'none')
      }
      // Inv assign ⇒ OTP always; plain enrol ⇒ optional checkbox
      const forceOtp = sysYes
      fd.append('require_otp', forceOtp || form.require_otp ? 'true' : 'false')
      if (photoFile) fd.append('photo', photoFile)
      const created = await api<any>('/api/scholars', { method: 'POST', body: fd })
      if (created?.pending_otp) {
        setOtpChallengeId(created.challenge_id)
        setOtpEmail(created.email || form.email)
        setOtpCode('')
        setOtpMessage(created.message || 'OTP sent')
        setEnrollOpen(false)
        setNotice(created.message || 'OTP sent — enter code to finish enrolment')
        return
      }
      setNotice(`Enrolled ${created.full_name}`)
      setForm({ ...EMPTY })
      setPhotoFile(null)
      if (photoRef.current) photoRef.current.value = ''
      setEnrollOpen(false)
      setTab('active')
      await load()
      await loadFacets()
    } catch (e: any) {
      setErr(e?.message || 'Enrol failed')
    } finally {
      setBusy(false)
    }
  }

  async function submitOtp(e: FormEvent) {
    e.preventDefault()
    if (!otpChallengeId || !otpCode.trim()) return
    setBusy(true)
    setErr('')
    try {
      const fd = new FormData()
      fd.append('challenge_id', otpChallengeId)
      fd.append('code', otpCode.trim())
      const r = await api<any>('/api/scholars/verify-otp', { method: 'POST', body: fd })
      setNotice(`Verified · enrolled ${r.scholar?.full_name || 'scholar'}`)
      setOtpChallengeId('')
      setOtpCode('')
      setOtpEmail('')
      setOtpMessage('')
      setForm({ ...EMPTY })
      setPhotoFile(null)
      if (photoRef.current) photoRef.current.value = ''
      setTab('active')
      await load()
      await loadFacets()
    } catch (e: any) {
      setErr(e?.message || 'OTP verification failed')
    } finally {
      setBusy(false)
    }
  }

  async function runRemove(e: FormEvent) {
    e.preventDefault()
    if (!selectedIds.length || !removeRemark.trim()) {
      setErr('Select scholars and enter a removal remark')
      return
    }
    setBusy(true)
    setErr('')
    try {
      const r = await api('/api/scholars/remove', {
        method: 'POST',
        body: JSON.stringify({ ids: selectedIds, remark: removeRemark.trim() }),
      })
      setNotice(`Removed ${r.removed} scholar(s)`)
      setRemoveOpen(false)
      setRemoveRemark('')
      setSelected({})
      setDetail(null)
      setTab('removed')
      await load()
    } catch (e: any) {
      setErr(e?.message || 'Remove failed')
    } finally {
      setBusy(false)
    }
  }

  async function runRestore(ids: string[] = selectedIds) {
    if (!ids.length) return
    if (!confirm(`Restore ${ids.length} scholar(s) to Active?`)) return
    setBusy(true)
    try {
      const r = await api('/api/scholars/restore', { method: 'POST', body: JSON.stringify({ ids }) })
      setNotice(`Restored ${r.restored} scholar(s)`)
      setSelected({})
      setDetail(null)
      setTab('active')
      await load()
    } catch (e: any) {
      setErr(e?.message || 'Restore failed')
    } finally {
      setBusy(false)
    }
  }

  async function runPurge(ids: string[] = selectedIds) {
    if (!ids.length) return
    if (!confirm(`Permanently delete ${ids.length} removed scholar(s)? This cannot be undone.`)) return
    setBusy(true)
    try {
      const r = await api('/api/scholars/purge', { method: 'POST', body: JSON.stringify({ ids }) })
      setNotice(`Permanently deleted ${r.deleted} scholar(s)`)
      setSelected({})
      setDetail(null)
      await load()
    } catch (e: any) {
      setErr(e?.message || 'Permanent delete failed')
    } finally {
      setBusy(false)
    }
  }

  async function runEmptyRemoved() {
    if (!total) return
    if (!confirm(`Empty Removed — permanently delete ALL ${total} removed scholar(s)?`)) return
    if (!confirm('Final confirm: delete every removed scholar forever?')) return
    setBusy(true)
    try {
      const r = await api('/api/scholars/empty-removed', { method: 'POST' })
      setNotice(`Emptied Removed — deleted ${r.deleted}`)
      setSelected({})
      setDetail(null)
      await load()
    } catch (e: any) {
      setErr(e?.message || 'Empty removed failed')
    } finally {
      setBusy(false)
    }
  }

  async function onImport(file: File | null) {
    if (!file || !canEdit) return
    const wantOtp = confirm(
      'Require email OTP verification for this import?\n\nOK = send OTP to each email (no auto-enrol until verified)\nCancel = import directly with no emails',
    )
    setBusy(true)
    setErr('')
    setNotice('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('require_otp', wantOtp ? 'true' : 'false')
      const r = await api('/api/scholars/import', { method: 'POST', body: fd })
      setNotice(
        `Import: ${r.created} created · ${r.updated} updated` +
          (r.pending_otp ? ` · ${r.pending_otp} OTP pending` : '') +
          (r.errors?.length ? ` · ${r.errors.length} errors` : ''),
      )
      if (r.errors?.length) setErr(r.errors.slice(0, 5).join('; '))
      if (wantOtp && r.otp_challenges?.length) {
        const first = r.otp_challenges[0]
        setOtpChallengeId(first.challenge_id)
        setOtpEmail(first.email)
        setOtpMessage(
          `${r.pending_otp} OTP email(s) sent. Enter OTP for ${first.full_name} (${first.email}). Verify others from their emails one by one if needed.`,
        )
        setOtpCode('')
      }
      setTab('active')
      await load()
      await loadFacets()
    } catch (e: any) {
      setErr(e?.message || 'Import failed')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function assignInvWithOtp(s: Scholar) {
    if (!canEdit) return
    const kind = prompt('Inventory kind: listed or non_list', s.inventory_kind === 'listed' ? 'listed' : 'non_list')
    if (!kind || !['listed', 'non_list'].includes(kind)) return
    let inventory_item_id = ''
    let inventory_label = ''
    if (kind === 'listed') {
      inventory_item_id = prompt('Inventory item UUID (from Inv Management)', s.inventory_item_id || '') || ''
      if (!inventory_item_id) return
    } else {
      inventory_label = prompt('Non-list inventory label / IC', s.inventory_label || '') || ''
      if (!inventory_label) return
    }
    setBusy(true)
    setErr('')
    try {
      const fd = new FormData()
      fd.append('inventory_kind', kind)
      fd.append('inventory_item_id', inventory_item_id)
      fd.append('inventory_label', inventory_label)
      const r = await api<any>(`/api/scholars/${s.id}/assign-inventory`, { method: 'POST', body: fd })
      setOtpChallengeId(r.challenge_id)
      setOtpEmail(r.email)
      setOtpMessage(r.message || 'OTP sent for inventory assign')
      setOtpCode('')
      setNotice(r.message || 'OTP sent')
    } catch (e: any) {
      setErr(e?.message || 'Assign OTP failed')
    } finally {
      setBusy(false)
    }
  }

  function exportUrl() {
    const qs = new URLSearchParams()
    qs.set('status', tab)
    if (labId) qs.set('lab_id', labId)
    return `/api/scholars/export.xlsx?${qs}`
  }

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Scholars</h2>
          <p>
            Enrol M.Tech / Ph.D. / Postdoc / staff · {total} {tab}
            {canEdit ? ' · enroll, import/export, remove/restore' : ' · view / export'}
          </p>
        </div>
      </div>

      <div className="tabs" style={{ marginBottom: 12 }}>
        <button className={tab === 'active' ? 'active' : ''} onClick={() => { setTab('active'); setSelected({}); setDetail(null) }}>
          Active
        </button>
        <button className={tab === 'removed' ? 'active' : ''} onClick={() => { setTab('removed'); setSelected({}); setDetail(null) }}>
          Removed
        </button>
      </div>

      <div className="card toolbar" style={{ marginBottom: 12, flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 220 }}>
          <span className="muted" style={{ fontSize: 12 }}>Lab</span>
          <select value={labId} onChange={(e) => setLabId(e.target.value)}>
            <option value="">All labs</option>
            {labs.map((l) => (
              <option key={l.id} value={l.id}>{labLabel(l)}</option>
            ))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 140 }}>
          <span className="muted" style={{ fontSize: 12 }}>Group</span>
          <select value={filterGroup} onChange={(e) => setFilterGroup(e.target.value)}>
            <option value="">All groups</option>
            {groups.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 160 }}>
          <span className="muted" style={{ fontSize: 12 }}>Faculty</span>
          <select value={filterFaculty} onChange={(e) => setFilterFaculty(e.target.value)}>
            <option value="">All faculty</option>
            {faculties.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        <button
          className="btn secondary"
          type="button"
          disabled={!filtersActive && !labId}
          onClick={() => { setFilterGroup(''); setFilterFaculty(''); setQ(''); setLabId('') }}
        >
          Clear filters
        </button>
      </div>

      <div className="card toolbar" style={{ marginBottom: 12, flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <input
          placeholder="Search name / ID / faculty / email…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ flex: '1 1 220px', minWidth: 180 }}
        />
        <button className="btn secondary" type="button" disabled={busy} onClick={() => void load()}>Refresh</button>
        {canEdit && tab === 'active' && (
          <>
            <button className="btn" type="button" disabled={!labId} onClick={() => setEnrollOpen(true)} title="Select a lab first">
              Enrol
            </button>
            <button className="btn danger" type="button" disabled={busy || !selectedIds.length} onClick={() => setRemoveOpen(true)}>
              Remove selected ({selectedIds.length})
            </button>
          </>
        )}
        {canEdit && tab === 'removed' && (
          <>
            <button className="btn" type="button" disabled={busy || !selectedIds.length} onClick={() => void runRestore(selectedIds)}>
              Restore selected ({selectedIds.length})
            </button>
            <button className="btn danger" type="button" disabled={busy || !selectedIds.length} onClick={() => void runPurge(selectedIds)}>
              Permanent delete selected ({selectedIds.length})
            </button>
            <button className="btn danger" type="button" disabled={busy || total < 1} onClick={() => void runEmptyRemoved()}>
              Empty removed ({total})
            </button>
          </>
        )}
        <button
          className="btn secondary"
          type="button"
          disabled={busy}
          onClick={() => downloadFile('/api/scholars/template.xlsx', 'labwatch-scholars-template.xlsx').catch((e) => setErr(e.message))}
        >
          Download template
        </button>
        <button
          className="btn secondary"
          type="button"
          disabled={busy}
          onClick={() => downloadFile(exportUrl(), `labwatch-scholars-${tab}.xlsx`).catch((e) => setErr(e.message))}
        >
          Export
        </button>
        {canEdit && (
          <>
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.csv"
              style={{ display: 'none' }}
              onChange={(e) => void onImport(e.target.files?.[0] || null)}
            />
            <button className="btn secondary" type="button" disabled={busy} onClick={() => fileRef.current?.click()}>
              Import
            </button>
          </>
        )}
      </div>

      {selectedLab && (
        <p className="muted" style={{ marginTop: 0 }}>
          Lab filter: <strong>{selectedLab.name}</strong>
          {selectedLab.room ? ` · Room ${selectedLab.room}` : ''}
        </p>
      )}
      {err && <p className="err">{err}</p>}
      {notice && <p className="muted">{notice}</p>}

      {enrollOpen && canEdit && (
        <form className="card" onSubmit={submitEnroll} style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Enrol into {selectedLab ? labLabel(selectedLab) : 'lab'}</h3>
          {!labId && <p className="err">Select a lab above first.</p>}
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 16, alignItems: 'start' }}>
            <div className="field" style={{ marginBottom: 0 }}>
              <label htmlFor="enrol-name">Name *</label>
              <input id="enrol-name" required style={{ width: '100%' }} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label htmlFor="enrol-id">ID</label>
              <input id="enrol-id" style={{ width: '100%' }} value={form.scholar_id} onChange={(e) => setForm({ ...form, scholar_id: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label htmlFor="enrol-group">Group</label>
              <input id="enrol-group" list="scholar-groups" style={{ width: '100%' }} value={form.group_name} onChange={(e) => setForm({ ...form, group_name: e.target.value })} />
              <datalist id="scholar-groups">{groups.map((g) => <option key={g} value={g} />)}</datalist>
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label htmlFor="enrol-faculty">Faculty</label>
              <input id="enrol-faculty" list="scholar-faculties" style={{ width: '100%' }} value={form.faculty} onChange={(e) => setForm({ ...form, faculty: e.target.value })} />
              <datalist id="scholar-faculties">{faculties.map((f) => <option key={f} value={f} />)}</datalist>
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label htmlFor="enrol-sys">System required</label>
              <select id="enrol-sys" style={{ width: '100%' }} value={form.system_required} onChange={(e) => setForm({ ...form, system_required: e.target.value, inventory_item_id: '', inventory_label: '', inv_search: '' })}>
                <option value="no">No</option>
                <option value="yes">Yes</option>
              </select>
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label htmlFor="enrol-email">Email</label>
              <input id="enrol-email" type="email" style={{ width: '100%' }} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label htmlFor="enrol-phone">Contact number</label>
              <input id="enrol-phone" style={{ width: '100%' }} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0, minWidth: 0 }}>
              <label htmlFor="enrol-photo">Photo</label>
              <input id="enrol-photo" ref={photoRef} type="file" accept="image/*" style={{ width: '100%', maxWidth: '100%' }} onChange={(e) => setPhotoFile(e.target.files?.[0] || null)} />
            </div>
          </div>

          {form.system_required !== 'yes' ? (
            <label className="check-row">
              <input
                type="checkbox"
                checked={form.require_otp}
                onChange={(e) => setForm({ ...form, require_otp: e.target.checked })}
              />
              <span>Require email OTP for this enrolment (optional)</span>
            </label>
          ) : (
            <p className="muted" style={{ margin: '16px 0 0' }}>
              Inventory assign requires email OTP (compulsory). Enter a valid email above.
            </p>
          )}

          {form.system_required === 'yes' && (
            <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
              <div className="toolbar" style={{ gap: 16, marginBottom: 12 }}>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <input type="radio" checked={form.inventory_mode === 'listed'} onChange={() => setForm({ ...form, inventory_mode: 'listed', inventory_item_id: '', inventory_label: '' })} />
                  From Inv list
                </label>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <input type="radio" checked={form.inventory_mode === 'non_list'} onChange={() => setForm({ ...form, inventory_mode: 'non_list', inventory_item_id: '', inventory_label: form.inv_search })} />
                  Non-list
                </label>
              </div>
              <div ref={suggestRef} className="field" style={{ marginBottom: 0, position: 'relative', maxWidth: 480 }}>
                <label htmlFor="enrol-inv">
                  {form.inventory_mode === 'listed' ? 'Search inventory' : 'Non-list inventory label'}
                </label>
                <input
                  id="enrol-inv"
                  style={{ width: '100%' }}
                  value={form.inventory_mode === 'listed' ? form.inv_search : form.inventory_label}
                  onChange={(e) => {
                    if (form.inventory_mode === 'listed') setForm({ ...form, inv_search: e.target.value, inventory_item_id: '', inventory_label: '' })
                    else setForm({ ...form, inventory_label: e.target.value, inv_search: e.target.value })
                  }}
                  onFocus={() => form.inventory_mode === 'listed' && suggestions.length && setShowSuggest(true)}
                />
                {form.inventory_mode === 'listed' && showSuggest && suggestions.length > 0 && (
                  <div className="card" style={{ position: 'absolute', zIndex: 20, left: 0, right: 0, top: '100%', marginTop: 4, maxHeight: 240, overflow: 'auto', padding: 0 }}>
                    {suggestions.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        className="btn secondary"
                        style={{ display: 'block', width: '100%', textAlign: 'left', borderRadius: 0, border: 'none', borderBottom: '1px solid var(--line)' }}
                        onClick={() => {
                          setForm({ ...form, inventory_item_id: s.id, inventory_label: s.ic_no, inv_search: `${s.ic_no} — ${s.item_name || 'item'}` })
                          setShowSuggest(false)
                        }}
                      >
                        <strong className="mono">{s.ic_no}</strong>
                        <div className="muted" style={{ fontSize: 12 }}>{s.item_name || '—'}</div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="toolbar" style={{ marginTop: 16, marginBottom: 0, gap: 8 }}>
            <button className="btn" disabled={busy || !labId} type="submit">{busy ? 'Saving…' : 'Save enrolment'}</button>
            <button className="btn secondary" type="button" onClick={() => setEnrollOpen(false)}>Cancel</button>
          </div>
        </form>
      )}

      {otpChallengeId && canEdit && (
        <form className="card" onSubmit={submitOtp} style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Verify email OTP</h3>
          <p className="muted">{otpMessage || `Code sent to ${otpEmail}`}</p>
          <label>
            OTP code
            <input
              required
              value={otpCode}
              onChange={(e) => setOtpCode(e.target.value)}
              placeholder="6-digit code"
              autoComplete="one-time-code"
            />
          </label>
          <div className="toolbar" style={{ marginTop: 12, gap: 8 }}>
            <button className="btn" disabled={busy} type="submit">{busy ? 'Verifying…' : 'Verify & complete'}</button>
            <button
              className="btn secondary"
              type="button"
              onClick={() => {
                setOtpChallengeId('')
                setOtpCode('')
                setOtpMessage('')
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {removeOpen && canEdit && tab === 'active' && (
        <form className="card" onSubmit={runRemove} style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Remove {selectedIds.length} scholar(s)</h3>
          <p className="muted">Soft-delete — moves to Removed with your remark.</p>
          <label>
            Removal remark (required)
            <textarea required rows={3} style={{ width: '100%' }} value={removeRemark} onChange={(e) => setRemoveRemark(e.target.value)} />
          </label>
          <div className="toolbar" style={{ marginTop: 12, gap: 8 }}>
            <button className="btn danger" disabled={busy} type="submit">Confirm remove</button>
            <button className="btn secondary" type="button" onClick={() => setRemoveOpen(false)}>Cancel</button>
          </div>
        </form>
      )}

      {detail && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="toolbar" style={{ justifyContent: 'space-between', gap: 8 }}>
            <h3 style={{ margin: 0 }}>Scholar detail</h3>
            <button className="btn secondary" type="button" onClick={() => setDetail(null)}>Close</button>
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 12 }}>
            {detail.has_photo ? <ScholarPhoto id={detail.id} /> : null}
            <div className="grid" style={{ flex: 1, gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10 }}>
              <div><div className="muted" style={{ fontSize: 12 }}>Name</div><strong>{detail.full_name}</strong></div>
              <div><div className="muted" style={{ fontSize: 12 }}>ID</div><span className="mono">{detail.scholar_id || '—'}</span></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Lab</div>{detail.lab_name}{detail.lab_room ? ` · Room ${detail.lab_room}` : ''}</div>
              <div><div className="muted" style={{ fontSize: 12 }}>Group</div>{detail.group_name || '—'}</div>
              <div><div className="muted" style={{ fontSize: 12 }}>Faculty</div>{detail.faculty || '—'}</div>
              <div><div className="muted" style={{ fontSize: 12 }}>System</div>{detail.system_required ? 'Yes' : 'No'}</div>
              <div><div className="muted" style={{ fontSize: 12 }}>Inventory</div>{detail.inventory_kind === 'none' ? '—' : `${detail.inventory_kind}: ${detail.inventory_label}`}</div>
              <div><div className="muted" style={{ fontSize: 12 }}>Email</div>{detail.email || '—'}</div>
              <div><div className="muted" style={{ fontSize: 12 }}>Phone</div>{detail.phone || '—'}</div>
              {tab === 'removed' && (
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Removal</div>
                  <div className="err">{detail.removal_remark || '—'}</div>
                  <div className="muted" style={{ fontSize: 12 }}>{detail.removed_by || '?'} · {ago(detail.removed_at)}</div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              {canEdit && (
                <th style={{ width: 36 }}>
                  <input type="checkbox" checked={allSelected} onChange={(e) => toggleAll(e.target.checked)} aria-label="Select all" />
                </th>
              )}
              <th></th>
              <th>Name</th>
              <th>ID</th>
              <th>Lab</th>
              <th>Group</th>
              <th>Faculty</th>
              <th>System</th>
              <th>Inventory</th>
              {tab === 'removed' ? <th>Removal remark</th> : <th>Email</th>}
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id}>
                {canEdit && (
                  <td>
                    <input
                      type="checkbox"
                      checked={!!selected[s.id]}
                      onChange={(e) =>
                        setSelected((prev) => {
                          const next = { ...prev }
                          if (e.target.checked) next[s.id] = true
                          else delete next[s.id]
                          return next
                        })
                      }
                      aria-label={`Select ${s.full_name}`}
                    />
                  </td>
                )}
                <td style={{ width: 52 }}>{s.has_photo ? <ScholarPhoto id={s.id} /> : <span className="muted">—</span>}</td>
                <td><strong>{s.full_name}</strong></td>
                <td className="mono">{s.scholar_id || '—'}</td>
                <td>
                  {s.lab_name}
                  {s.lab_room ? <div className="muted" style={{ fontSize: 12 }}>Room {s.lab_room}</div> : null}
                </td>
                <td>{s.group_name || '—'}</td>
                <td>{s.faculty || '—'}</td>
                <td>{s.system_required ? 'Yes' : 'No'}</td>
                <td>
                  {s.inventory_kind === 'none' && <span className="muted">—</span>}
                  {s.inventory_kind === 'listed' && <span className="mono">{s.inventory_label}</span>}
                  {s.inventory_kind === 'non_list' && (
                    <><span className="badge INFO">non-list</span> <span className="mono">{s.inventory_label}</span></>
                  )}
                </td>
                {tab === 'removed' ? (
                  <td>
                    <div className="err">{s.removal_remark || '—'}</div>
                    <div className="muted" style={{ fontSize: 12 }}>{s.removed_by || '?'} · {ago(s.removed_at)}</div>
                  </td>
                ) : (
                  <td>{s.email || '—'}</td>
                )}
                <td className="row-actions">
                  <button className="btn secondary" type="button" onClick={() => setDetail(s)}>Details</button>
                  {canEdit && tab === 'active' && (
                    <button className="btn secondary" type="button" disabled={busy} onClick={() => void assignInvWithOtp(s)}>
                      Assign inv (OTP)
                    </button>
                  )}
                  {canEdit && tab === 'removed' && (
                    <>
                      <button className="btn secondary" type="button" disabled={busy} onClick={() => void runRestore([s.id])}>Restore</button>
                      <button className="btn danger" type="button" disabled={busy} onClick={() => void runPurge([s.id])}>Delete forever</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={11} className="muted" style={{ padding: 16 }}>
                  {tab === 'removed'
                    ? 'No removed scholars. Soft-removed enrolments appear here for restore or permanent delete.'
                    : 'No scholars yet. Download template (has example row), fill real data, Import — or Enrol one by one.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}
