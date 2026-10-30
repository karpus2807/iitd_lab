import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ago, api, currentUser, downloadFile } from '../api'

type InvItem = {
  id: string
  ic_no: string
  item_name: string
  item_description: string
  net_effective_value: number | null
  inventory_type: string
  inventory_location: string
  gis_date: string | null
  inv_type: string
  remark: string
  assigned_to?: string
  status: string
  removed_at?: string | null
  removed_by?: string | null
  removal_remark?: string | null
  registered?: boolean
  assigned?: boolean
  machine_id?: string | null
  machine_hostname?: string | null
}

type Suggest = {
  id: string
  ic_no: string
  item_name: string
  inventory_location: string
  inv_type: string
}

const EMPTY_FORM = {
  ic_no: '',
  item_name: '',
  item_description: '',
  net_effective_value: '' as string | number,
  inventory_type: '',
  inventory_location: '',
  gis_date: '',
  inv_type: '',
  remark: '',
  assigned_to: '',
}

function money(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

function LinkStatus({ item }: { item: InvItem }) {
  const registered = !!item.registered
  const assigned = !!item.assigned
  if (!registered && !assigned) return <span className="muted">—</span>
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {registered && (
        <span className="badge ONLINE" title={item.machine_hostname || item.machine_id || 'LabWatch machine'}>
          <i className="dot" />
          Registered
        </span>
      )}
      {assigned && (
        <span className="badge INFO" title={item.assigned_to || 'Personal / issued'}>
          <i className="dot" />
          Assigned{item.assigned_to ? `: ${item.assigned_to}` : ''}
        </span>
      )}
    </div>
  )
}

export default function Inventory() {
  const role = currentUser()?.role
  const canEdit = role === 'ADMIN' || role === 'OPERATOR'
  const [tab, setTab] = useState<'active' | 'removed'>('active')
  const [rows, setRows] = useState<InvItem[]>([])
  const [total, setTotal] = useState(0)
  const [q, setQ] = useState('')
  const [filterType, setFilterType] = useState('')
  const [filterLocation, setFilterLocation] = useState('')
  const [filterInvType, setFilterInvType] = useState('')
  const [filterLink, setFilterLink] = useState('any')
  const [facetTypes, setFacetTypes] = useState<string[]>([])
  const [facetLocations, setFacetLocations] = useState<string[]>([])
  const [facetInvTypes, setFacetInvTypes] = useState<string[]>([])
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [suggestions, setSuggestions] = useState<Suggest[]>([])
  const [showSuggest, setShowSuggest] = useState(false)
  const [editing, setEditing] = useState<InvItem | null>(null)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchFields, setBatchFields] = useState({
    inventory_type: '',
    inventory_location: '',
    inv_type: '',
    remark: '',
  })
  const [removeOpen, setRemoveOpen] = useState(false)
  const [removeRemark, setRemoveRemark] = useState('')
  const suggestRef = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const filtersActive = !!(filterType || filterLocation || filterInvType || (filterLink && filterLink !== 'any'))

  const loadFacets = useCallback(async () => {
    try {
      const data = await api<{
        inventory_types: string[]
        inventory_locations: string[]
        inv_types: string[]
      }>(`/api/inventory/facets?status=${tab}`)
      setFacetTypes(data.inventory_types || [])
      setFacetLocations(data.inventory_locations || [])
      setFacetInvTypes(data.inv_types || [])
    } catch {
      setFacetTypes([])
      setFacetLocations([])
      setFacetInvTypes([])
    }
  }, [tab])

  const load = useCallback(async () => {
    setErr('')
    try {
      const qs = new URLSearchParams()
      qs.set('status', tab)
      qs.set('limit', '2000')
      if (q.trim()) qs.set('q', q.trim())
      if (filterType) qs.set('inventory_type', filterType)
      if (filterLocation) qs.set('inventory_location', filterLocation)
      if (filterInvType) qs.set('inv_type', filterInvType)
      if (filterLink && filterLink !== 'any') qs.set('link', filterLink)
      const data = await api<{ items: InvItem[]; total: number }>(`/api/inventory?${qs}`)
      setRows(data.items || [])
      setTotal(data.total || 0)
      setSelected((prev) => {
        const next: Record<string, boolean> = {}
        for (const r of data.items || []) {
          if (prev[r.id]) next[r.id] = true
        }
        return next
      })
    } catch (e: any) {
      setErr(e?.message || 'Could not load inventory')
      setRows([])
      setTotal(0)
    }
  }, [tab, q, filterType, filterLocation, filterInvType, filterLink])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    void loadFacets()
  }, [loadFacets])

  useEffect(() => {
    const needle = q.trim()
    if (needle.length < 1 || tab !== 'active') {
      setSuggestions([])
      return
    }
    const t = window.setTimeout(() => {
      api<Suggest[]>(`/api/inventory/suggest?q=${encodeURIComponent(needle)}&limit=15`)
        .then((rows) => {
          setSuggestions(rows || [])
          setShowSuggest(true)
        })
        .catch(() => setSuggestions([]))
    }, 220)
    return () => window.clearTimeout(t)
  }, [q, tab])

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!suggestRef.current?.contains(e.target as Node)) setShowSuggest(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const selectedIds = useMemo(() => rows.filter((r) => selected[r.id]).map((r) => r.id), [rows, selected])
  const allSelected = rows.length > 0 && rows.every((r) => selected[r.id])

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

  function openAdd() {
    setAdding(true)
    setEditing(null)
    setForm({ ...EMPTY_FORM })
  }

  function openEdit(item: InvItem) {
    setAdding(false)
    setEditing(item)
    setForm({
      ic_no: item.ic_no || '',
      item_name: item.item_name || '',
      item_description: item.item_description || '',
      net_effective_value: item.net_effective_value ?? '',
      inventory_type: item.inventory_type || '',
      inventory_location: item.inventory_location || '',
      gis_date: item.gis_date || '',
      inv_type: item.inv_type || '',
      remark: item.remark || '',
      assigned_to: item.assigned_to || '',
    })
  }

  function payloadFromForm() {
    const val =
      form.net_effective_value === '' || form.net_effective_value == null
        ? null
        : Number(form.net_effective_value)
    return {
      ic_no: form.ic_no.trim(),
      item_name: form.item_name.trim(),
      item_description: form.item_description.trim(),
      net_effective_value: Number.isFinite(val as number) ? val : null,
      inventory_type: form.inventory_type.trim(),
      inventory_location: form.inventory_location.trim(),
      gis_date: form.gis_date || null,
      inv_type: form.inv_type.trim(),
      remark: form.remark.trim(),
      assigned_to: form.assigned_to.trim(),
    }
  }

  async function saveForm(e: FormEvent) {
    e.preventDefault()
    if (!canEdit) return
    setBusy(true)
    setErr('')
    setNotice('')
    try {
      const body = payloadFromForm()
      if (!body.ic_no) throw new Error('IC No. is required')
      if (editing) {
        await api(`/api/inventory/${editing.id}`, { method: 'PATCH', body: JSON.stringify(body) })
        setNotice(`Updated ${body.ic_no}`)
      } else {
        await api('/api/inventory', { method: 'POST', body: JSON.stringify(body) })
        setNotice(`Added ${body.ic_no}`)
      }
      setAdding(false)
      setEditing(null)
      await load()
    } catch (e: any) {
      setErr(e?.message || 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  async function runBatch(e: FormEvent) {
    e.preventDefault()
    if (!selectedIds.length) return
    const fields: Record<string, string> = {}
    for (const [k, v] of Object.entries(batchFields)) {
      if (v.trim()) fields[k] = v.trim()
    }
    if (!Object.keys(fields).length) {
      setErr('Set at least one batch field')
      return
    }
    setBusy(true)
    setErr('')
    try {
      const r = await api('/api/inventory/batch', {
        method: 'POST',
        body: JSON.stringify({ ids: selectedIds, fields }),
      })
      setNotice(`Batch updated ${r.updated} item(s)`)
      setBatchOpen(false)
      await load()
    } catch (e: any) {
      setErr(e?.message || 'Batch update failed')
    } finally {
      setBusy(false)
    }
  }

  async function runRemove(e: FormEvent) {
    e.preventDefault()
    if (!selectedIds.length) return
    if (!removeRemark.trim()) {
      setErr('Removal remark is required')
      return
    }
    setBusy(true)
    setErr('')
    try {
      const r = await api('/api/inventory/remove', {
        method: 'POST',
        body: JSON.stringify({ ids: selectedIds, remark: removeRemark.trim() }),
      })
      setNotice(`Removed ${r.removed} item(s)`)
      setRemoveOpen(false)
      setRemoveRemark('')
      setSelected({})
      setTab('removed')
      await load()
    } catch (e: any) {
      setErr(e?.message || 'Remove failed')
    } finally {
      setBusy(false)
    }
  }

  async function runRestore(ids: string[] = selectedIds, label?: string) {
    if (!ids.length) return
    const who = label || `${ids.length} item(s)`
    if (!confirm(`Restore ${who} back to Active?`)) return
    setBusy(true)
    setErr('')
    setNotice('')
    try {
      const r = await api('/api/inventory/restore', {
        method: 'POST',
        body: JSON.stringify({ ids }),
      })
      setNotice(`Restored ${r.restored} item(s)`)
      setSelected({})
      setTab('active')
      await load()
    } catch (e: any) {
      setErr(e?.message || 'Restore failed')
    } finally {
      setBusy(false)
    }
  }

  async function runPurge(ids: string[] = selectedIds, label?: string) {
    if (!ids.length) return
    const who = label || `${ids.length} removed item(s)`
    if (!confirm(`Permanently delete ${who}? This cannot be undone.`)) return
    setBusy(true)
    setErr('')
    setNotice('')
    try {
      const r = await api('/api/inventory/purge', {
        method: 'POST',
        body: JSON.stringify({ ids }),
      })
      setNotice(`Permanently deleted ${r.deleted} item(s)`)
      setSelected({})
      await load()
    } catch (e: any) {
      setErr(e?.message || 'Permanent delete failed')
    } finally {
      setBusy(false)
    }
  }

  async function runEmptyRemoved() {
    if (!total) {
      setErr('Removed list is already empty')
      return
    }
    if (
      !confirm(
        `Empty Removed — permanently delete ALL ${total} removed item(s)? This cannot be undone.`,
      )
    ) {
      return
    }
    if (!confirm('Final confirm: delete every removed inventory row forever?')) return
    setBusy(true)
    setErr('')
    setNotice('')
    try {
      const r = await api('/api/inventory/empty-removed', { method: 'POST' })
      setNotice(`Emptied Removed — permanently deleted ${r.deleted} item(s)`)
      setSelected({})
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
      const r = await api('/api/inventory/import', { method: 'POST', body: fd })
      setNotice(
        `Import: ${r.created} created · ${r.updated} updated · ${r.restored} restored` +
          (r.errors?.length ? ` · ${r.errors.length} errors` : ''),
      )
      if (r.errors?.length) setErr(r.errors.slice(0, 5).join('; '))
      await load()
    } catch (e: any) {
      setErr(e?.message || 'Import failed')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <>
      <div className="topbar">
        <div>
          <h2>Inv Management</h2>
          <p>
            Lab asset registry (IC No.) · {total} {tab}
            {canEdit
              ? ' · add, edit, import/export, soft-remove, restore, permanent delete'
              : ' · view / export'}
          </p>
        </div>
      </div>

      <div className="tabs" style={{ marginBottom: 12 }}>
        <button
          className={tab === 'active' ? 'active' : ''}
          onClick={() => {
            setTab('active')
            setSelected({})
          }}
        >
          Active
        </button>
        <button
          className={tab === 'removed' ? 'active' : ''}
          onClick={() => {
            setTab('removed')
            setSelected({})
          }}
        >
          Removed
        </button>
      </div>

      <div className="card toolbar" style={{ marginBottom: 12, flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 140 }}>
          <span className="muted" style={{ fontSize: 12 }}>Type</span>
          <select value={filterType} onChange={(e) => setFilterType(e.target.value)}>
            <option value="">All types</option>
            <option value="__blank__">(blank)</option>
            {facetTypes.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 160 }}>
          <span className="muted" style={{ fontSize: 12 }}>Location</span>
          <select value={filterLocation} onChange={(e) => setFilterLocation(e.target.value)}>
            <option value="">All locations</option>
            <option value="__blank__">(blank)</option>
            {facetLocations.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 140 }}>
          <span className="muted" style={{ fontSize: 12 }}>Inv Type</span>
          <select value={filterInvType} onChange={(e) => setFilterInvType(e.target.value)}>
            <option value="">All inv types</option>
            <option value="__blank__">(blank)</option>
            {facetInvTypes.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 160 }}>
          <span className="muted" style={{ fontSize: 12 }}>Link status</span>
          <select value={filterLink} onChange={(e) => setFilterLink(e.target.value)}>
            <option value="any">Any status</option>
            <option value="registered">Registered</option>
            <option value="assigned">Assigned</option>
            <option value="registered_assigned">Registered + Assigned</option>
            <option value="unlinked">Not registered</option>
          </select>
        </label>
        <button
          className="btn secondary"
          type="button"
          disabled={!filtersActive && !q}
          onClick={() => {
            setFilterType('')
            setFilterLocation('')
            setFilterInvType('')
            setFilterLink('any')
            setQ('')
          }}
        >
          Clear filters
        </button>
      </div>

      <div className="card toolbar" style={{ marginBottom: 12, flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <div ref={suggestRef} style={{ position: 'relative', flex: '1 1 260px', minWidth: 200 }}>
          <input
            placeholder="Search IC No. / name / location…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onFocus={() => suggestions.length && setShowSuggest(true)}
            style={{ width: '100%' }}
          />
          {showSuggest && suggestions.length > 0 && tab === 'active' && (
            <div
              className="card"
              style={{
                position: 'absolute',
                zIndex: 20,
                left: 0,
                right: 0,
                top: '100%',
                marginTop: 4,
                maxHeight: 260,
                overflow: 'auto',
                padding: 0,
              }}
            >
              {suggestions.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className="btn secondary"
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    borderRadius: 0,
                    border: 'none',
                    borderBottom: '1px solid var(--line)',
                  }}
                  onClick={() => {
                    setQ(s.ic_no)
                    setShowSuggest(false)
                    setSelected((prev) => ({ ...prev, [s.id]: true }))
                  }}
                >
                  <strong className="mono">{s.ic_no}</strong>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {s.item_name || '—'}
                    {s.inventory_location ? ` · ${s.inventory_location}` : ''}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
        <button className="btn secondary" disabled={busy} onClick={() => void load()}>
          Refresh
        </button>
        {canEdit && tab === 'active' && (
          <>
            <button className="btn" disabled={busy} onClick={openAdd}>
              Add inv.
            </button>
            <button className="btn secondary" disabled={busy || !selectedIds.length} onClick={() => setBatchOpen(true)}>
              Batch edit ({selectedIds.length})
            </button>
            <button className="btn danger" disabled={busy || !selectedIds.length} onClick={() => setRemoveOpen(true)}>
              Remove ({selectedIds.length})
            </button>
          </>
        )}
        {canEdit && tab === 'removed' && (
          <>
            <button
              className="btn"
              disabled={busy || !selectedIds.length}
              onClick={() => void runRestore(selectedIds)}
              title="Restore selected items back to Active"
            >
              Restore selected ({selectedIds.length})
            </button>
            <button
              className="btn danger"
              disabled={busy || !selectedIds.length}
              onClick={() => void runPurge(selectedIds)}
              title="Permanently delete only the selected removed items"
            >
              Permanent delete selected ({selectedIds.length})
            </button>
            <button
              className="btn danger"
              disabled={busy || total < 1}
              onClick={() => void runEmptyRemoved()}
              title="Permanently delete every item in Removed"
            >
              Empty removed ({total})
            </button>
          </>
        )}
        <button
          className="btn secondary"
          disabled={busy}
          onClick={() => downloadFile('/api/inventory/template.xlsx', 'labwatch-inventory-template.xlsx').catch((e) => setErr(e.message))}
        >
          Download template
        </button>
        <button
          className="btn secondary"
          disabled={busy}
          onClick={() =>
            downloadFile(`/api/inventory/export.xlsx?status=${tab}`, `labwatch-inventory-${tab}.xlsx`).catch((e) =>
              setErr(e.message),
            )
          }
        >
          Export
        </button>
        {canEdit && (
          <>
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
              style={{ display: 'none' }}
              onChange={(e) => void onImport(e.target.files?.[0] || null)}
            />
            <button className="btn secondary" disabled={busy} onClick={() => fileRef.current?.click()}>
              Import
            </button>
          </>
        )}
      </div>

      {err && <p className="err">{err}</p>}
      {notice && <p className="muted" style={{ marginBottom: 8 }}>{notice}</p>}

      {(adding || editing) && canEdit && (
        <form className="card" onSubmit={saveForm} style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>{editing ? `Edit ${editing.ic_no}` : 'Add inventory'}</h3>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
            <label>
              IC No.
              <input required value={form.ic_no} onChange={(e) => setForm({ ...form, ic_no: e.target.value })} disabled={!!editing} />
            </label>
            <label>
              Item Name
              <input value={form.item_name} onChange={(e) => setForm({ ...form, item_name: e.target.value })} />
            </label>
            <label>
              Inventory Type
              <input value={form.inventory_type} onChange={(e) => setForm({ ...form, inventory_type: e.target.value })} placeholder="Lab / Personal" />
            </label>
            <label>
              Inv Type
              <input value={form.inv_type} onChange={(e) => setForm({ ...form, inv_type: e.target.value })} placeholder="Institute / IRD" />
            </label>
            <label>
              Inventory Location
              <input value={form.inventory_location} onChange={(e) => setForm({ ...form, inventory_location: e.target.value })} />
            </label>
            <label>
              GIS Date
              <input type="date" value={form.gis_date} onChange={(e) => setForm({ ...form, gis_date: e.target.value })} />
            </label>
            <label>
              Net Effective Value (Rs.)
              <input
                type="number"
                step="0.01"
                value={form.net_effective_value}
                onChange={(e) => setForm({ ...form, net_effective_value: e.target.value })}
              />
            </label>
          </div>
          <label style={{ display: 'block', marginTop: 12 }}>
            Item Description
            <textarea
              rows={3}
              style={{ width: '100%' }}
              value={form.item_description}
              onChange={(e) => setForm({ ...form, item_description: e.target.value })}
            />
          </label>
          <label style={{ display: 'block', marginTop: 12 }}>
            remark
            <input value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
          </label>
          <label style={{ display: 'block', marginTop: 12 }}>
            Assigned to (student / person)
            <input
              value={form.assigned_to}
              onChange={(e) => setForm({ ...form, assigned_to: e.target.value })}
              placeholder="Leave blank if unassigned"
            />
          </label>
          <div className="toolbar" style={{ marginTop: 12, gap: 8 }}>
            <button className="btn" disabled={busy} type="submit">
              {busy ? 'Saving…' : 'Save'}
            </button>
            <button
              className="btn secondary"
              type="button"
              onClick={() => {
                setAdding(false)
                setEditing(null)
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {batchOpen && canEdit && (
        <form className="card" onSubmit={runBatch} style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Batch edit {selectedIds.length} items</h3>
          <p className="muted">Only filled fields are applied. IC No. cannot be batch-changed.</p>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
            <label>
              Inventory Type
              <input value={batchFields.inventory_type} onChange={(e) => setBatchFields({ ...batchFields, inventory_type: e.target.value })} />
            </label>
            <label>
              Inventory Location
              <input value={batchFields.inventory_location} onChange={(e) => setBatchFields({ ...batchFields, inventory_location: e.target.value })} />
            </label>
            <label>
              Inv Type
              <input value={batchFields.inv_type} onChange={(e) => setBatchFields({ ...batchFields, inv_type: e.target.value })} />
            </label>
            <label>
              remark
              <input value={batchFields.remark} onChange={(e) => setBatchFields({ ...batchFields, remark: e.target.value })} />
            </label>
          </div>
          <div className="toolbar" style={{ marginTop: 12, gap: 8 }}>
            <button className="btn" disabled={busy} type="submit">
              Apply
            </button>
            <button className="btn secondary" type="button" onClick={() => setBatchOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {removeOpen && canEdit && (
        <form className="card" onSubmit={runRemove} style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Remove {selectedIds.length} item(s)</h3>
          <p className="muted">Soft-delete — items move to Removed with your remark.</p>
          <label>
            Removal remark (required)
            <textarea required rows={3} style={{ width: '100%' }} value={removeRemark} onChange={(e) => setRemoveRemark(e.target.value)} />
          </label>
          <div className="toolbar" style={{ marginTop: 12, gap: 8 }}>
            <button className="btn danger" disabled={busy} type="submit">
              Confirm remove
            </button>
            <button className="btn secondary" type="button" onClick={() => setRemoveOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
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
              <th>IC No.</th>
              <th>Item Name</th>
              <th>Type</th>
              <th>Location</th>
              <th>Inv Type</th>
              <th>Value (Rs.)</th>
              <th>GIS Date</th>
              {tab === 'removed' ? <th>Removal remark</th> : <th>remark</th>}
              <th>Status</th>
              {canEdit && <th></th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                {canEdit && (
                  <td>
                    <input
                      type="checkbox"
                      checked={!!selected[r.id]}
                      onChange={(e) =>
                        setSelected((prev) => {
                          const next = { ...prev }
                          if (e.target.checked) next[r.id] = true
                          else delete next[r.id]
                          return next
                        })
                      }
                      aria-label={`Select ${r.ic_no}`}
                    />
                  </td>
                )}
                <td className="mono">{r.ic_no}</td>
                <td>
                  <div>{r.item_name || '—'}</div>
                  {r.item_description ? (
                    <div className="muted" style={{ fontSize: 12, maxWidth: 320 }}>
                      {r.item_description.length > 120 ? `${r.item_description.slice(0, 120)}…` : r.item_description}
                    </div>
                  ) : null}
                </td>
                <td>{r.inventory_type || '—'}</td>
                <td>{r.inventory_location || '—'}</td>
                <td>{r.inv_type || '—'}</td>
                <td className="mono">{money(r.net_effective_value)}</td>
                <td className="mono">{r.gis_date || '—'}</td>
                {tab === 'removed' ? (
                  <td>
                    <div className="err">{r.removal_remark || '—'}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {r.removed_by || '?'} · {ago(r.removed_at)}
                    </div>
                  </td>
                ) : (
                  <td>{r.remark || '—'}</td>
                )}
                <td>
                  <LinkStatus item={r} />
                </td>
                {canEdit && tab === 'active' && (
                  <td className="row-actions">
                    <button className="btn secondary" type="button" onClick={() => openEdit(r)}>
                      Edit
                    </button>
                  </td>
                )}
                {canEdit && tab === 'removed' && (
                  <td className="row-actions">
                    <button
                      className="btn secondary"
                      type="button"
                      disabled={busy}
                      onClick={() => void runRestore([r.id], r.ic_no)}
                    >
                      Restore
                    </button>
                    <button
                      className="btn danger"
                      type="button"
                      disabled={busy}
                      onClick={() => void runPurge([r.id], r.ic_no)}
                    >
                      Delete forever
                    </button>
                  </td>
                )}
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={10} className="muted" style={{ padding: 16 }}>
                  {tab === 'removed'
                    ? 'No removed inventory. Soft-removed items appear here for restore or permanent delete.'
                    : 'No inventory items. Download the template, fill it, then Import — or Add inv.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}
