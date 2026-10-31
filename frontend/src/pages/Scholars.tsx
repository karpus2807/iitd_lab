import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from 'react'
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
  bio_id: string
  group_name: string
  faculty: string
  system_required: boolean
  approved: boolean
  approved_at?: string | null
  no_dues: boolean
  no_dues_at?: string | null
  inventory_kind: string
  inventory_item_id: string | null
  inventory_label: string
  inventory_item_name: string
  inventory_assigned_at?: string | null
  email: string
  phone: string
  has_photo: boolean
  has_inv_verify_doc?: boolean
  status: string
  notes?: string
  removed_at?: string | null
  removed_by?: string | null
  removal_remark?: string | null
}

type DashLab = {
  id: string
  name: string
  room?: string
  building?: string
  scholars: number
  approved: number
  pending: number
  no_dues: number
  with_inventory: number
  machines: number
}

type DashSummary = {
  scholars: number
  approved: number
  pending: number
  no_dues: number
  with_inventory: number
  machines: number
  labs: DashLab[]
}

type DashScholar = Scholar & {
  inventory?: {
    id: string | null
    ic_no: string
    item_name: string
    inventory_type: string
    inventory_location: string
    assigned_to: string
  } | null
}

type DashLabDetail = {
  lab: { id: string; name: string; room?: string; building?: string }
  machines: number
  scholars: DashScholar[]
  counts: {
    scholars: number
    approved: number
    pending: number
    no_dues: number
    with_inventory: number
  }
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
  bio_id: '',
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
  verify_method: 'otp' as 'otp' | 'document',
}

function rowTone(s: Scholar): CSSProperties | undefined {
  if (s.status === 'removed') return undefined
  if (s.no_dues) return { background: 'rgba(220, 38, 38, 0.12)' }
  if (s.approved) return { background: 'rgba(22, 163, 74, 0.12)' }
  return undefined
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
  const [tab, setTab] = useState<'dashboard' | 'active' | 'removed' | 'logs'>('dashboard')
  const [reports, setReports] = useState<any[]>([])
  const [reportsTotal, setReportsTotal] = useState(0)
  const [reportDetail, setReportDetail] = useState<any | null>(null)
  const [reportFilter, setReportFilter] = useState('all')
  const [customClearDays, setCustomClearDays] = useState('30')
  const [logsBusy, setLogsBusy] = useState(false)
  const [labs, setLabs] = useState<Lab[]>([])
  const [labId, setLabId] = useState('')
  const [rows, setRows] = useState<Scholar[]>([])
  const [total, setTotal] = useState(0)
  const [dash, setDash] = useState<DashSummary | null>(null)
  const [dashLab, setDashLab] = useState<DashLabDetail | null>(null)
  const [dashBusy, setDashBusy] = useState(false)
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
  const [enrolDocFile, setEnrolDocFile] = useState<File | null>(null)
  const [otpChallengeId, setOtpChallengeId] = useState('')
  const [otpEmail, setOtpEmail] = useState('')
  const [otpCode, setOtpCode] = useState('')
  const [otpMessage, setOtpMessage] = useState('')
  const [editFor, setEditFor] = useState<Scholar | null>(null)
  const photoRef = useRef<HTMLInputElement>(null)
  const enrolDocRef = useRef<HTMLInputElement>(null)
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
    if (tab === 'dashboard' || tab === 'logs') return
    const qs = new URLSearchParams()
    qs.set('status', tab)
    if (labId) qs.set('lab_id', labId)
    const data = await api<{ groups: string[]; faculties: string[] }>(`/api/scholars/facets?${qs}`)
    setGroups(data.groups || [])
    setFaculties(data.faculties || [])
  }, [labId, tab])

  const load = useCallback(async () => {
    if (tab === 'dashboard' || tab === 'logs') return
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

  const loadDashboard = useCallback(async () => {
    setDashBusy(true)
    setErr('')
    try {
      const data = await api<DashSummary>('/api/scholars/dashboard')
      setDash(data)
    } catch (e: any) {
      setErr(e?.message || 'Could not load scholar dashboard')
      setDash(null)
    } finally {
      setDashBusy(false)
    }
  }, [])

  async function openDashLab(id: string) {
    setDashBusy(true)
    setErr('')
    try {
      const data = await api<DashLabDetail>(`/api/scholars/dashboard/${id}`)
      setDashLab(data)
    } catch (e: any) {
      setErr(e?.message || 'Could not load lab scholars')
      setDashLab(null)
    } finally {
      setDashBusy(false)
    }
  }

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
    if (tab === 'dashboard') {
      setDashLab(null)
      void loadDashboard()
    }
  }, [tab, loadDashboard])

  const loadReports = useCallback(async () => {
    setLogsBusy(true)
    setErr('')
    try {
      const qs = new URLSearchParams()
      qs.set('area', 'scholars')
      qs.set('limit', '100')
      if (reportFilter && reportFilter !== 'all') qs.set('action', reportFilter)
      const data = await api<{ items: any[]; total: number }>(`/api/reports?${qs}`)
      setReports(data.items || [])
      setReportsTotal(data.total || 0)
    } catch (e: any) {
      setErr(e?.message || 'Could not load reports')
      setReports([])
      setReportsTotal(0)
    } finally {
      setLogsBusy(false)
    }
  }, [reportFilter])

  useEffect(() => {
    if (tab === 'logs') void loadReports()
  }, [tab, loadReports])

  async function openReport(id: string) {
    setLogsBusy(true)
    try {
      const data = await api(`/api/reports/${id}`)
      setReportDetail(data)
    } catch (e: any) {
      setErr(e?.message || 'Could not open report')
    } finally {
      setLogsBusy(false)
    }
  }

  async function clearReports(days: number) {
    const label = days <= 0 ? 'ALL reports' : `reports older than ${days} day(s)`
    if (!confirm(`Clear ${label}? This cannot be undone.`)) return
    setLogsBusy(true)
    try {
      const r = await api<{ deleted: number }>('/api/reports/clear', {
        method: 'POST',
        body: JSON.stringify({ older_than_days: days }),
      })
      setNotice(`Cleared ${r.deleted} report(s)`)
      setReportDetail(null)
      await loadReports()
    } catch (e: any) {
      setErr(e?.message || 'Clear failed')
    } finally {
      setLogsBusy(false)
    }
  }

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
      fd.append('bio_id', form.bio_id.trim())
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
      if (sysYes) {
        fd.append('verify_method', form.verify_method)
        if (form.verify_method === 'document') {
          if (!enrolDocFile) throw new Error('Upload a PDF verification document')
          fd.append('document', enrolDocFile)
        }
        fd.append('require_otp', form.verify_method === 'otp' ? 'true' : 'false')
      } else {
        fd.append('require_otp', form.require_otp ? 'true' : 'false')
        fd.append('verify_method', 'otp')
      }
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
      setEnrolDocFile(null)
      if (photoRef.current) photoRef.current.value = ''
      if (enrolDocRef.current) enrolDocRef.current.value = ''
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
    setBusy(true)
    setErr('')
    setNotice('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await api('/api/scholars/import', { method: 'POST', body: fd })
      setNotice(
        `Import: ${r.created} created · ${r.updated} updated` +
          (r.errors?.length ? ` · ${r.errors.length} errors` : '') +
          (r.report_id ? ' · open Logs & reports for full row detail' : ''),
      )
      if (r.errors?.length) setErr(r.errors.map((e: string) => e).join('\n'))
      if (r.report) {
        setReportDetail(r.report)
        setTab('logs')
      } else {
        setTab('active')
        await load()
        await loadFacets()
      }
    } catch (e: any) {
      setErr(e?.message || 'Import failed')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function openEdit(s: Scholar) {
    if (!canEdit) return
    setEditFor(s)
    setLabId(s.lab_id)
    setForm({
      ...EMPTY,
      full_name: s.full_name || '',
      scholar_id: s.scholar_id || '',
      bio_id: s.bio_id || '',
      group_name: s.group_name || 'M.Tech',
      faculty: s.faculty || '',
      system_required: s.system_required ? 'yes' : 'no',
      inventory_mode: s.inventory_kind === 'non_list' ? 'non_list' : 'listed',
      inventory_item_id: s.inventory_item_id || '',
      inventory_label: s.inventory_label || '',
      inv_search: s.inventory_kind === 'listed' ? (s.inventory_label || '') : (s.inventory_label || ''),
      email: s.email || '',
      phone: s.phone || '',
      notes: s.notes || '',
    })
    setEnrollOpen(false)
    setErr('')
    setNotice('')
  }

  async function submitEdit(e: FormEvent) {
    e.preventDefault()
    if (!editFor || !canEdit) return
    setBusy(true)
    setErr('')
    try {
      const sysYes = form.system_required === 'yes'
      const payload: Record<string, unknown> = {
        lab_id: labId || editFor.lab_id,
        full_name: form.full_name.trim(),
        scholar_id: form.scholar_id.trim(),
        bio_id: form.bio_id.trim(),
        group_name: form.group_name.trim(),
        faculty: form.faculty.trim(),
        email: form.email.trim(),
        phone: form.phone.trim(),
        notes: form.notes.trim(),
        system_required: sysYes,
        inventory_kind: sysYes ? (form.inventory_mode === 'listed' ? 'listed' : 'non_list') : 'none',
        inventory_item_id: sysYes && form.inventory_mode === 'listed' ? form.inventory_item_id || null : null,
        inventory_label: sysYes
          ? (form.inventory_mode === 'listed' ? form.inventory_label : (form.inventory_label.trim() || form.inv_search.trim()))
          : '',
      }
      const fd = new FormData()
      fd.append('payload', JSON.stringify(payload))
      if (photoFile) fd.append('photo', photoFile)
      const updated = await api<Scholar>(`/api/scholars/${editFor.id}`, { method: 'PATCH', body: fd })
      setNotice(`Updated ${updated.full_name}`)
      setEditFor(null)
      setForm({ ...EMPTY })
      setPhotoFile(null)
      if (photoRef.current) photoRef.current.value = ''
      await load()
      await loadFacets()
    } catch (e: any) {
      setErr(e?.message || 'Update failed')
    } finally {
      setBusy(false)
    }
  }

  async function approveScholar(s: Scholar) {
    if (!canEdit) return
    setBusy(true)
    setErr('')
    try {
      await api(`/api/scholars/${s.id}/approve`, { method: 'POST' })
      setNotice(`Approved ${s.full_name} · active in lab`)
      await load()
    } catch (e: any) {
      setErr(e?.message || 'Approve failed')
    } finally {
      setBusy(false)
    }
  }

  async function setNoDues(s: Scholar, flag: boolean) {
    if (!canEdit) return
    setBusy(true)
    setErr('')
    try {
      const fd = new FormData()
      fd.append('no_dues', flag ? 'true' : 'false')
      await api(`/api/scholars/${s.id}/no-dues`, { method: 'POST', body: fd })
      setNotice(flag ? `No dues marked for ${s.full_name}` : `No dues revoked for ${s.full_name}`)
      await load()
    } catch (e: any) {
      setErr(e?.message || 'No-dues update failed')
    } finally {
      setBusy(false)
    }
  }

  function openRemoveOne(s: Scholar) {
    setSelected({ [s.id]: true })
    setRemoveRemark('')
    setRemoveOpen(true)
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
            {tab === 'dashboard'
              ? 'Lab-wise scholar counts, inventory assignments, and drill-down'
              : tab === 'logs'
                ? 'Import/export activity reports — every row result, errors, and clear history'
                : `Enrol M.Tech / Ph.D. / Postdoc / staff · ${total} ${tab}${canEdit ? ' · enroll, import/export, remove/restore' : ' · view / export'}`}
          </p>
        </div>
      </div>

      <div className="tabs" style={{ marginBottom: 12 }}>
        <button
          className={tab === 'dashboard' ? 'active' : ''}
          onClick={() => { setTab('dashboard'); setSelected({}); setDetail(null); setEnrollOpen(false); setEditFor(null); setRemoveOpen(false) }}
        >
          Dashboard
        </button>
        <button className={tab === 'active' ? 'active' : ''} onClick={() => { setTab('active'); setSelected({}); setDetail(null); setDashLab(null) }}>
          Active
        </button>
        <button className={tab === 'removed' ? 'active' : ''} onClick={() => { setTab('removed'); setSelected({}); setDetail(null); setDashLab(null) }}>
          Removed
        </button>
        <button className={tab === 'logs' ? 'active' : ''} onClick={() => { setTab('logs'); setSelected({}); setDetail(null); setDashLab(null); setEnrollOpen(false); setEditFor(null); setRemoveOpen(false) }}>
          Logs & reports
        </button>
      </div>

      {err && <pre className="err" style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>{err}</pre>}
      {notice && tab !== 'dashboard' && <p className="muted">{notice}</p>}

      {tab === 'dashboard' && (
        <>
          {!dash && dashBusy && <p className="muted">Loading scholar dashboard…</p>}
          {dash && (
            <>
              <div className="grid stats">
                <div className="card stat"><div className="label">Scholars</div><div className="value">{dash.scholars}</div></div>
                <div className="card stat online"><div className="label">Approved</div><div className="value">{dash.approved}</div></div>
                <div className="card stat"><div className="label">Pending</div><div className="value">{dash.pending}</div></div>
                <div className="card stat offline"><div className="label">No dues</div><div className="value">{dash.no_dues}</div></div>
                <div className="card stat"><div className="label">With inventory</div><div className="value">{dash.with_inventory}</div></div>
                <div className="card stat"><div className="label">Lab machines</div><div className="value">{dash.machines}</div></div>
              </div>
              <div className="split" style={{ marginTop: 16 }}>
                <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
                  <h3 className="section-title" style={{ padding: 16, margin: 0 }}>Labs</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>Lab</th>
                        <th>Scholars</th>
                        <th>Approved</th>
                        <th>Pending</th>
                        <th>No dues</th>
                        <th>Inv assigned</th>
                        <th>Machines</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dash.labs.map((l) => (
                        <tr
                          key={l.id}
                          className="clickable"
                          style={dashLab?.lab.id === l.id ? { outline: '1px solid var(--accent, #3b82f6)' } : undefined}
                          onClick={() => void openDashLab(l.id)}
                        >
                          <td>
                            <strong>{l.name}</strong>
                            {(l.room || l.building) ? (
                              <div className="muted" style={{ fontSize: 12 }}>
                                {[l.building, l.room ? `Room ${l.room}` : ''].filter(Boolean).join(' · ')}
                              </div>
                            ) : null}
                          </td>
                          <td className="mono">{l.scholars}</td>
                          <td className="mono">{l.approved}</td>
                          <td className="mono">{l.pending}</td>
                          <td className="mono">{l.no_dues}</td>
                          <td className="mono">{l.with_inventory}</td>
                          <td className="mono">{l.machines}</td>
                        </tr>
                      ))}
                      {!dash.labs.length && (
                        <tr><td colSpan={7} className="muted" style={{ padding: 16 }}>No labs yet.</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
                <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
                  <div className="section-head" style={{ padding: 16, margin: 0 }}>
                    <h3 className="section-title" style={{ margin: 0 }}>
                      {dashLab ? `${dashLab.lab.name} · scholars` : 'Lab detail'}
                    </h3>
                    {dashLab && (
                      <button className="btn secondary" type="button" onClick={() => setDashLab(null)}>Close</button>
                    )}
                  </div>
                  {!dashLab && !dashBusy && (
                    <p className="muted" style={{ padding: 16, margin: 0 }}>Click a lab to see scholars and assigned inventory.</p>
                  )}
                  {dashBusy && !dashLab && <p className="muted" style={{ padding: 16 }}>Loading…</p>}
                  {dashLab && (
                    <>
                      <div className="toolbar" style={{ padding: '0 16px 12px', gap: 12, flexWrap: 'wrap' }}>
                        <span className="muted">{dashLab.counts.scholars} scholars</span>
                        <span className="muted">{dashLab.counts.approved} approved</span>
                        <span className="muted">{dashLab.counts.with_inventory} with inv</span>
                        <span className="muted">{dashLab.machines} machines in lab</span>
                        <button
                          className="btn secondary"
                          type="button"
                          onClick={() => {
                            setLabId(dashLab.lab.id)
                            setTab('active')
                            setDashLab(null)
                          }}
                        >
                          Open in Active
                        </button>
                      </div>
                      <table>
                        <thead>
                          <tr>
                            <th>Name</th>
                            <th>ID</th>
                            <th>Bio-ID</th>
                            <th>Group</th>
                            <th>Status</th>
                            <th>Inventory</th>
                            <th>Assigned</th>
                            <th>Faculty</th>
                          </tr>
                        </thead>
                        <tbody>
                          {dashLab.scholars.map((s) => (
                            <tr key={s.id} style={rowTone(s)}>
                              <td><strong>{s.full_name}</strong></td>
                              <td className="mono">{s.scholar_id || '—'}</td>
                              <td className="mono">{s.bio_id || '—'}</td>
                              <td>{s.group_name || '—'}</td>
                              <td>
                                {s.no_dues ? (
                                  <span className="badge CRITICAL">no dues</span>
                                ) : s.approved ? (
                                  <span className="badge ONLINE">active</span>
                                ) : (
                                  <span className="badge INFO">pending</span>
                                )}
                              </td>
                              <td>
                                {!s.inventory ? (
                                  <span className="muted">—</span>
                                ) : (
                                  <>
                                    <span className="mono">{s.inventory.ic_no || s.inventory_label || '—'}</span>
                                    {s.inventory.item_name ? (
                                      <div className="muted" style={{ fontSize: 12 }}>{s.inventory.item_name}</div>
                                    ) : s.inventory_kind === 'non_list' ? (
                                      <div className="muted" style={{ fontSize: 12 }}>non-list</div>
                                    ) : null}
                                  </>
                                )}
                              </td>
                              <td className="muted" style={{ whiteSpace: 'nowrap' }}>
                                {s.inventory_assigned_at ? ago(s.inventory_assigned_at) : '—'}
                              </td>
                              <td>{s.faculty || '—'}</td>
                            </tr>
                          ))}
                          {!dashLab.scholars.length && (
                            <tr><td colSpan={8} className="muted" style={{ padding: 16 }}>No active scholars in this lab.</td></tr>
                          )}
                        </tbody>
                      </table>
                    </>
                  )}
                </div>
              </div>
            </>
          )}
        </>
      )}

      {tab === 'logs' && (
        <>
          <div className="card toolbar" style={{ marginBottom: 12, flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
            <select value={reportFilter} onChange={(e) => setReportFilter(e.target.value)}>
              <option value="all">All actions</option>
              <option value="import">Import</option>
              <option value="export">Export</option>
              <option value="remove">Remove</option>
              <option value="restore">Restore</option>
              <option value="empty_removed">Empty removed</option>
            </select>
            <button className="btn secondary" type="button" disabled={logsBusy} onClick={() => void loadReports()}>Refresh</button>
            <span className="muted" style={{ fontSize: 13 }}>{reportsTotal} report(s)</span>
            {canEdit && (
              <>
                <button className="btn danger" type="button" disabled={logsBusy} onClick={() => void clearReports(7)}>Clear &gt;1 week</button>
                <button className="btn danger" type="button" disabled={logsBusy} onClick={() => void clearReports(14)}>Clear &gt;2 weeks</button>
                <button className="btn danger" type="button" disabled={logsBusy} onClick={() => void clearReports(30)}>Clear &gt;1 month</button>
                <input
                  style={{ width: 72 }}
                  value={customClearDays}
                  onChange={(e) => setCustomClearDays(e.target.value)}
                  title="Custom days"
                  placeholder="days"
                />
                <button
                  className="btn danger"
                  type="button"
                  disabled={logsBusy}
                  onClick={() => {
                    const n = Number(customClearDays)
                    if (!Number.isFinite(n) || n < 1) {
                      setErr('Enter custom days ≥ 1')
                      return
                    }
                    void clearReports(Math.floor(n))
                  }}
                >
                  Clear custom days
                </button>
                <button className="btn danger" type="button" disabled={logsBusy} onClick={() => void clearReports(0)}>Clear all</button>
              </>
            )}
          </div>

          {reportDetail && (
            <div className="card" style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                <div>
                  <h3 style={{ marginTop: 0, marginBottom: 4 }}>
                    {reportDetail.action} · {reportDetail.filename || 'activity'}
                  </h3>
                  <p className="muted" style={{ margin: 0, fontSize: 13 }}>
                    {ago(reportDetail.created_at)} · {reportDetail.username || '—'}
                    {reportDetail.summary
                      ? ` · ${Object.entries(reportDetail.summary)
                          .filter(([k]) => !['error_messages'].includes(k))
                          .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
                          .join(' · ')}`
                      : ''}
                  </p>
                </div>
                <button className="btn secondary" type="button" onClick={() => setReportDetail(null)}>Close detail</button>
              </div>
              {Array.isArray(reportDetail.summary?.error_messages) && reportDetail.summary.error_messages.length > 0 && (
                <div className="err" style={{ marginTop: 12, whiteSpace: 'pre-wrap' }}>
                  {reportDetail.summary.error_messages.join('\n')}
                </div>
              )}
              <div style={{ marginTop: 12, overflow: 'auto', maxHeight: 420 }}>
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Name</th>
                      <th>ID</th>
                      <th>Bio</th>
                      <th>Lab</th>
                      <th>Result</th>
                      <th>Message</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(reportDetail.rows || []).map((r: any, i: number) => (
                      <tr key={`${reportDetail.id}-${i}`} style={r.result === 'error' ? { background: 'rgba(220,38,38,0.08)' } : undefined}>
                        <td className="mono">{r.row ?? i + 1}</td>
                        <td>{r.full_name || '—'}</td>
                        <td className="mono">{r.scholar_id || '—'}</td>
                        <td className="mono">{r.bio_id || '—'}</td>
                        <td>{r.lab || '—'}</td>
                        <td>
                          <strong className={r.result === 'error' ? 'err' : r.result === 'created' ? '' : 'muted'}>
                            {r.result || '—'}
                          </strong>
                        </td>
                        <td style={{ fontSize: 13 }}>{r.message || '—'}</td>
                      </tr>
                    ))}
                    {!(reportDetail.rows || []).length && (
                      <tr><td colSpan={7} className="muted" style={{ padding: 16 }}>No per-row detail in this report.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="card" style={{ padding: 0 }}>
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Action</th>
                  <th>File / note</th>
                  <th>User</th>
                  <th>Summary</th>
                  <th>Rows</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {reports.map((r) => (
                  <tr key={r.id}>
                    <td className="muted" style={{ whiteSpace: 'nowrap' }}>{ago(r.created_at)}</td>
                    <td><strong>{r.action}</strong></td>
                    <td className="mono">{r.filename || '—'}</td>
                    <td>{r.username || '—'}</td>
                    <td style={{ fontSize: 13 }}>
                      {r.summary
                        ? Object.entries(r.summary)
                            .filter(([k]) => !['error_messages'].includes(k))
                            .slice(0, 6)
                            .map(([k, v]) => `${k}:${v}`)
                            .join(' · ')
                        : '—'}
                    </td>
                    <td className="mono">{r.row_count ?? 0}</td>
                    <td>
                      <button className="btn secondary" type="button" disabled={logsBusy} onClick={() => void openReport(r.id)}>
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
                {!reports.length && (
                  <tr>
                    <td colSpan={7} className="muted" style={{ padding: 16 }}>
                      {logsBusy ? 'Loading…' : 'No import/export reports yet. Import or export scholars to create one.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab !== 'dashboard' && tab !== 'logs' && (
      <>
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
              <label htmlFor="enrol-id">ID (school-wide unique)</label>
              <input id="enrol-id" style={{ width: '100%' }} value={form.scholar_id} onChange={(e) => setForm({ ...form, scholar_id: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label htmlFor="enrol-bio">Bio-ID (unique in this lab)</label>
              <input id="enrol-bio" style={{ width: '100%' }} value={form.bio_id} onChange={(e) => setForm({ ...form, bio_id: e.target.value })} />
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
            <div style={{ margin: '16px 0 0' }}>
              <p className="muted" style={{ marginTop: 0 }}>
                Inventory assign needs verification — primary email OTP, or secondary PDF proof (faculty mail attachment).
              </p>
              <div className="toolbar" style={{ gap: 16, marginBottom: 8 }}>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <input
                    type="radio"
                    checked={form.verify_method === 'otp'}
                    onChange={() => setForm({ ...form, verify_method: 'otp' })}
                  />
                  Email OTP (primary)
                </label>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <input
                    type="radio"
                    checked={form.verify_method === 'document'}
                    onChange={() => setForm({ ...form, verify_method: 'document' })}
                  />
                  PDF document
                </label>
              </div>
              {form.verify_method === 'otp' ? (
                <p className="muted" style={{ margin: 0, fontSize: 13 }}>Enter a valid email above — OTP is sent before inventory links.</p>
              ) : (
                <label className="field" style={{ marginBottom: 0, maxWidth: 420 }}>
                  Verification PDF
                  <input
                    ref={enrolDocRef}
                    type="file"
                    accept="application/pdf,.pdf"
                    style={{ width: '100%' }}
                    onChange={(e) => setEnrolDocFile(e.target.files?.[0] || null)}
                  />
                </label>
              )}
            </div>
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

      {editFor && canEdit && (
        <form className="card" onSubmit={submitEdit} style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Edit · {editFor.full_name}</h3>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 16, alignItems: 'start' }}>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Lab</label>
              <select style={{ width: '100%' }} value={labId} onChange={(e) => setLabId(e.target.value)}>
                {labs.map((l) => (
                  <option key={l.id} value={l.id}>{labLabel(l)}</option>
                ))}
              </select>
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Name *</label>
              <input required style={{ width: '100%' }} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>ID (school-wide unique)</label>
              <input style={{ width: '100%' }} value={form.scholar_id} onChange={(e) => setForm({ ...form, scholar_id: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Bio-ID (unique in lab)</label>
              <input style={{ width: '100%' }} value={form.bio_id} onChange={(e) => setForm({ ...form, bio_id: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Group</label>
              <input style={{ width: '100%' }} value={form.group_name} onChange={(e) => setForm({ ...form, group_name: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Faculty</label>
              <input style={{ width: '100%' }} value={form.faculty} onChange={(e) => setForm({ ...form, faculty: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Email</label>
              <input type="email" style={{ width: '100%' }} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Phone</label>
              <input style={{ width: '100%' }} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>System required</label>
              <select style={{ width: '100%' }} value={form.system_required} onChange={(e) => setForm({ ...form, system_required: e.target.value })}>
                <option value="no">No</option>
                <option value="yes">Yes</option>
              </select>
            </div>
            {form.system_required === 'yes' && (
              <div className="field" style={{ marginBottom: 0 }}>
                <label>{form.inventory_mode === 'listed' ? 'Inventory IC' : 'Non-list label'}</label>
                <input
                  style={{ width: '100%' }}
                  value={form.inventory_mode === 'listed' ? form.inv_search : form.inventory_label}
                  onChange={(e) => {
                    if (form.inventory_mode === 'listed') setForm({ ...form, inv_search: e.target.value, inventory_label: e.target.value })
                    else setForm({ ...form, inventory_label: e.target.value })
                  }}
                />
              </div>
            )}
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Notes</label>
              <input style={{ width: '100%' }} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Photo</label>
              <input ref={photoRef} type="file" accept="image/*" style={{ width: '100%' }} onChange={(e) => setPhotoFile(e.target.files?.[0] || null)} />
            </div>
          </div>
          <div className="toolbar" style={{ marginTop: 12, gap: 8 }}>
            <button className="btn" disabled={busy} type="submit">{busy ? 'Saving…' : 'Save changes'}</button>
            <button className="btn secondary" type="button" onClick={() => { setEditFor(null); setForm({ ...EMPTY }) }}>Cancel</button>
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
              <div><div className="muted" style={{ fontSize: 12 }}>Bio-ID</div><span className="mono">{detail.bio_id || '—'}</span></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Lab</div>{detail.lab_name}{detail.lab_room ? ` · Room ${detail.lab_room}` : ''}</div>
              <div><div className="muted" style={{ fontSize: 12 }}>Group</div>{detail.group_name || '—'}</div>
              <div><div className="muted" style={{ fontSize: 12 }}>Faculty</div>{detail.faculty || '—'}</div>
              <div><div className="muted" style={{ fontSize: 12 }}>Approved</div>{detail.approved ? 'Yes (green)' : 'Pending'}</div>
              <div><div className="muted" style={{ fontSize: 12 }}>No dues</div>{detail.no_dues ? 'Yes (red)' : 'No'}</div>
              <div><div className="muted" style={{ fontSize: 12 }}>System</div>{detail.system_required ? 'Yes' : 'No'}</div>
              <div><div className="muted" style={{ fontSize: 12 }}>Inventory</div>{detail.inventory_kind === 'none' ? '—' : `${detail.inventory_kind}: ${detail.inventory_label}`}</div>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>Inv verify doc</div>
                {detail.has_inv_verify_doc ? (
                  <a href={`/api/scholars/${detail.id}/inv-verify-doc`} target="_blank" rel="noreferrer" onClick={(e) => {
                    e.preventDefault()
                    const token = getToken()
                    void fetch(`/api/scholars/${detail.id}/inv-verify-doc`, {
                      headers: token ? { Authorization: `Bearer ${token}` } : {},
                    }).then(async (res) => {
                      if (!res.ok) throw new Error('Download failed')
                      const blob = await res.blob()
                      const url = URL.createObjectURL(blob)
                      window.open(url, '_blank')
                      setTimeout(() => URL.revokeObjectURL(url), 60_000)
                    }).catch((err) => setErr(err?.message || 'Could not open PDF'))
                  }}>Open PDF</a>
                ) : (
                  <span className="muted">—</span>
                )}
              </div>
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
              <th>Bio-ID</th>
              <th>Lab</th>
              <th>Group</th>
              <th>Faculty</th>
              <th>Status</th>
              <th>No dues</th>
              <th>Inventory</th>
              {tab === 'removed' ? <th>Removal remark</th> : <th>Email</th>}
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} style={rowTone(s)}>
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
                <td className="mono">{s.bio_id || '—'}</td>
                <td>
                  {s.lab_name}
                  {s.lab_room ? <div className="muted" style={{ fontSize: 12 }}>Room {s.lab_room}</div> : null}
                </td>
                <td>{s.group_name || '—'}</td>
                <td>{s.faculty || '—'}</td>
                <td>
                  {s.no_dues ? (
                    <span className="badge CRITICAL">left / no dues</span>
                  ) : s.approved ? (
                    <span className="badge ONLINE">active</span>
                  ) : (
                    <span className="badge INFO">pending</span>
                  )}
                </td>
                <td>{s.no_dues ? 'Yes' : 'No'}</td>
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
                    <>
                      {!s.approved && !s.no_dues && (
                        <button className="btn" type="button" disabled={busy} onClick={() => void approveScholar(s)}>
                          Approve
                        </button>
                      )}
                      <button className="btn secondary" type="button" disabled={busy} onClick={() => openEdit(s)}>
                        Edit
                      </button>
                      {!s.no_dues ? (
                        <button className="btn secondary" type="button" disabled={busy} onClick={() => void setNoDues(s, true)}>
                          No dues
                        </button>
                      ) : (
                        <button className="btn secondary" type="button" disabled={busy} onClick={() => void setNoDues(s, false)}>
                          Revoke no dues
                        </button>
                      )}
                      <button className="btn danger" type="button" disabled={busy} onClick={() => openRemoveOne(s)}>
                        Remove
                      </button>
                    </>
                  )}
                  {canEdit && tab === 'removed' && (
                    <button className="btn secondary" type="button" disabled={busy} onClick={() => void runRestore([s.id])}>Restore</button>
                  )}
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={13} className="muted" style={{ padding: 16 }}>
                  {tab === 'removed'
                    ? 'No removed scholars. Soft-removed enrolments appear here for restore, or Empty removed to delete all forever.'
                    : 'No scholars yet. Download template (has example row), fill real data, Import — or Enrol one by one.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      </>
      )}
    </>
  )
}
