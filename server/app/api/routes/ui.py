"""Self-contained Infra + Updates pages (work even when the SPA image is old)."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api/ui", tags=["ui"])

PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>LabWatch · Infra</title>
  <style>
    :root { --bg:#0c1218; --card:#141c24; --line:#2a3846; --text:#e7eef5; --muted:#8b9aab; --accent:#3dbe9a; --crit:#e15d5d; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: system-ui, sans-serif; background:var(--bg); color:var(--text); }
    header { display:flex; gap:16px; align-items:center; padding:16px 24px; border-bottom:1px solid var(--line); }
    header a { color:var(--muted); text-decoration:none; }
    header a.active { color:var(--accent); }
    main { padding:24px; max-width:1200px; margin:0 auto; }
    h1 { margin:0 0 8px; font-size:22px; }
    p.muted, .muted { color:var(--muted); }
    .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; margin-bottom:16px; }
    table { width:100%; border-collapse:collapse; font-size:14px; }
    th { text-align:left; color:var(--muted); font-weight:500; padding:8px; border-bottom:1px solid var(--line); }
    td { padding:8px; border-bottom:1px solid var(--line); vertical-align:top; }
    input, select, textarea { width:100%; background:#1b2530; border:1px solid var(--line); color:var(--text); border-radius:8px; padding:8px; }
    button { background:var(--accent); color:#062018; border:0; border-radius:8px; padding:8px 12px; font-weight:600; cursor:pointer; }
    button.sec { background:#1b2530; color:var(--text); border:1px solid var(--line); }
    button.danger { background:var(--crit); color:#fff; }
    .row { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
    .row > * { flex:1; min-width:140px; }
    .err { color:var(--crit); }
    .ok { color:var(--accent); }
    .badge { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 8px; font-size:12px; margin-right:6px; }
  </style>
</head>
<body>
<header>
  <strong>LabWatch</strong>
  <a href="/" >Dashboard</a>
  <a href="/api/ui/infra" id="nav-infra">Infra</a>
  <a href="/api/ui/updates" id="nav-updates">Updates</a>
</header>
<main id="root"><p class="muted">Loading…</p></main>
<script>
const PAGE = location.pathname.includes("/updates") ? "updates" : "infra";
document.getElementById(PAGE === "updates" ? "nav-updates" : "nav-infra").classList.add("active");
const token = localStorage.getItem("lw_access");
if (!token) { location.href = "/login"; }

async function api(path, opt={}) {
  const headers = Object.assign({"Content-Type":"application/json", Authorization:"Bearer "+token}, opt.headers||{});
  const res = await fetch(path, Object.assign({}, opt, {headers}));
  if (res.status === 401) { location.href = "/login"; throw new Error("Unauthorized"); }
  if (!res.ok) {
    let d = res.statusText;
    try { const j = await res.json(); d = j.detail || JSON.stringify(j); } catch(e) {}
    throw new Error(typeof d === "string" ? d : JSON.stringify(d));
  }
  if (res.status === 204) return null;
  return res.json();
}

function el(html) { const d = document.createElement("div"); d.innerHTML = html; return d.firstElementChild; }

async function renderInfra() {
  const root = document.getElementById("root");
  try {
    const [labs, machines] = await Promise.all([api("/api/labs"), api("/api/machines")]);
    root.innerHTML = "";
    root.append(el("<h1>Infrastructure</h1>"));
    root.append(el("<p class='muted'>Edit lab names, building, room, and assign machines. Placeholder names like DAIR LAB can be renamed or deleted.</p>"));
    const form = el(`<form class="card row">
      <input name="name" placeholder="Lab name" required/>
      <input name="building" placeholder="Building"/>
      <input name="room" placeholder="Room"/>
      <input name="description" placeholder="Description"/>
      <button>Add lab</button>
    </form>`);
    form.onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(form);
      await api("/api/labs", {method:"POST", body: JSON.stringify(Object.fromEntries(f))});
      renderInfra();
    };
    root.append(form);
    const table = el("<div class='card' style='padding:0;overflow:auto'><table><thead><tr><th>Name</th><th>Building</th><th>Room</th><th>Description</th><th>Hosts</th><th></th></tr></thead><tbody></tbody></table></div>");
    const tb = table.querySelector("tbody");
    labs.forEach(lab => {
      const tr = el(`<tr>
        <td><input value="${esc(lab.name)}" data-k="name"/></td>
        <td><input value="${esc(lab.building||"")}" data-k="building"/></td>
        <td><input value="${esc(lab.room||"")}" data-k="room"/></td>
        <td><input value="${esc(lab.description||"")}" data-k="description"/></td>
        <td class="muted">${lab.online_count||0}/${lab.machine_count||0}</td>
        <td><button type="button" class="sec save">Save</button> ${lab.protected ? "" : '<button type="button" class="danger del">Delete</button>'}</td>
      </tr>`);
      tr.querySelector(".save").onclick = async () => {
        const body = {};
        tr.querySelectorAll("input").forEach(i => body[i.dataset.k] = i.value);
        await api("/api/labs/"+lab.id, {method:"PATCH", body: JSON.stringify(body)});
        renderInfra();
      };
      const del = tr.querySelector(".del");
      if (del) del.onclick = async () => {
        if (!confirm("Delete "+lab.name+"? Machines move to Unassigned.")) return;
        await api("/api/labs/"+lab.id, {method:"DELETE"});
        renderInfra();
      };
      tb.append(tr);
    });
    root.append(table);
    const mt = el("<div class='card' style='padding:0;overflow:auto'><h3 class='muted' style='padding:12px'>Machines</h3><table><thead><tr><th>Host</th><th>Display name</th><th>Lab</th><th></th></tr></thead><tbody></tbody></table></div>");
    const mb = mt.querySelector("tbody");
    machines.forEach(m => {
      const opts = ['<option value="">Unassigned</option>'].concat(labs.map(l => `<option value="${l.id}" ${m.lab_id===l.id?"selected":""}>${esc(l.name)}</option>`)).join("");
      const tr = el(`<tr>
        <td>${esc(m.hostname)}</td>
        <td><input value="${esc(m.display_name||"")}"/></td>
        <td><select>${opts}</select></td>
        <td><button type="button" class="sec">Save</button></td>
      </tr>`);
      tr.querySelector("button").onclick = async () => {
        await api("/api/machines/"+m.id, {method:"PATCH", body: JSON.stringify({display_name: tr.querySelector("input").value, lab_id: tr.querySelector("select").value || null})});
        renderInfra();
      };
      mb.append(tr);
    });
    root.append(mt);
  } catch (e) {
    root.innerHTML = "<p class='err'>"+esc(e.message)+"</p>";
  }
}

async function renderUpdates() {
  const root = document.getElementById("root");
  root.innerHTML = "<h1>Server updates</h1><p class='muted'>Last GitHub releases. Select a tag to update or downgrade.</p>";
  try {
    const data = await api("/api/admin/updates");
    const box = el("<div class='card'></div>");
    box.innerHTML = `<p><span class="badge">Current ${esc(data.current && data.current.tag)}</span><span class="badge">Latest ${esc(data.latest && data.latest.tag)}</span></p>`;
    (data.builds||[]).forEach(b => {
      const row = el(`<div class="card"><strong>${esc(b.tag)}</strong> ${b.is_current?"<span class='badge'>Current</span>":""} ${b.is_latest?"<span class='badge'>Latest</span>":""}<div class="muted">${esc(b.name||"")}</div><button class="sec">${b.action==="downgrade"?"Downgrade": b.action==="current"?"Reinstall":"Update"}</button></div>`);
      row.querySelector("button").onclick = async () => {
        if (!confirm("Apply "+b.tag+"?")) return;
        await api("/api/admin/updates/apply", {method:"POST", body: JSON.stringify({tag: b.tag})});
        renderUpdates();
      };
      box.append(row);
    });
    if (data.status && data.status.message) box.append(el("<p>"+esc(data.status.message)+"</p>"));
    if (!(data.builds||[]).length) box.append(el("<p class='muted'>GitHub list empty. After proxy works: git fetch origin --tags && git checkout v1.1.5</p>"));
    root.append(box);
  } catch (e) {
    root.innerHTML += "<p class='err'>"+esc(e.message)+"</p><p class='muted'>Updates API is missing on this image. After GitHub fetch, checkout v1.1.5 or copy server/app updates modules into the API container.</p>";
  }
}

function esc(s){ return String(s??"").replace(/[&<>"'`]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','`':'&#96;'}[c])); }
PAGE === "updates" ? renderUpdates() : renderInfra();
</script>
</body>
</html>
"""


@router.get("/infra", response_class=HTMLResponse)
async def infra_page():
    return HTMLResponse(PAGE)


@router.get("/updates", response_class=HTMLResponse)
async def updates_page():
    return HTMLResponse(PAGE)
