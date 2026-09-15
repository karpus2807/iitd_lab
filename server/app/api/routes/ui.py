"""Management UI served by the API (Labs + Updates). Login form is static HTML so JS bugs cannot blank the page."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api/ui", tags=["ui"])

PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>LabWatch</title>
  <style>
    :root { --bg:#0c1218; --card:#141c24; --line:#2a3846; --text:#e7eef5; --muted:#8b9aab; --accent:#3dbe9a; --crit:#e15d5d; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: system-ui, sans-serif; background:var(--bg); color:var(--text); }
    header { display:flex; gap:16px; align-items:center; flex-wrap:wrap; padding:16px 24px; border-bottom:1px solid var(--line); }
    header a { color:var(--muted); text-decoration:none; }
    header a.active { color:var(--accent); }
    main { padding:24px; max-width:1280px; margin:0 auto; }
    h1 { margin:0 0 8px; font-size:22px; }
    .muted { color:var(--muted); }
    .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; margin-bottom:16px; }
    input, select { background:#1b2530; border:1px solid var(--line); color:var(--text); border-radius:8px; padding:8px; min-width:0; width:100%; }
    button { background:var(--accent); color:#062018; border:0; border-radius:8px; padding:8px 12px; font-weight:600; cursor:pointer; }
    button.sec { background:#1b2530; color:var(--text); border:1px solid var(--line); }
    button.danger { background:var(--crit); color:#fff; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:8px; }
    .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
    .err { color:var(--crit); }
    .badge { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 8px; font-size:12px; }
    table { width:100%; border-collapse:collapse; font-size:14px; }
    th, td { text-align:left; padding:8px; border-bottom:1px solid var(--line); vertical-align:top; }
    .login { max-width:380px; margin:8vh auto; }
    .hidden { display:none !important; }
  </style>
</head>
<body>
<header>
  <strong>LabWatch</strong>
  <nav id="links" class="hidden">
    <a href="/labs">Labs</a>
    <a href="/updates">Updates</a>
    <a href="/api/ui/admin">Users</a>
    <a href="/machines">Machines</a>
    <a href="#" id="signout">Sign out</a>
  </nav>
</header>
<main>
  <p id="banner" class="err"></p>
  <form id="login-form" class="card login">
    <h1>Sign in</h1>
    <p class="muted">Labs editor, users, and server Updates</p>
    <div class="grid" style="grid-template-columns:1fr">
      <input name="username" placeholder="Username" value="admin" autocomplete="username"/>
      <input name="password" type="password" placeholder="Password" autocomplete="current-password"/>
    </div>
    <p class="err" id="le"></p>
    <button style="margin-top:12px">Sign in</button>
  </form>
  <div id="workspace" class="hidden"></div>
</main>
<script>
const PAGE = location.pathname.indexOf("/updates") >= 0 ? "updates" : location.pathname.indexOf("/admin") >= 0 ? "admin" : "labs";
const LAB_KEYS = ["name","code","department","building","floor","room","capacity","incharge","phone","email","description"];
function $(id){ return document.getElementById(id); }
function esc(s){ return String(s==null?"":s).replace(/[&<>"'`]/g, function(c){ return ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;","`":"&#96;"})[c]; }); }
function token(){ return localStorage.getItem("lw_access"); }
function show(el, on){ if (el) el.classList.toggle("hidden", !on); }
function banner(msg){ $("banner").textContent = msg || ""; }
function saveSession(data){
  localStorage.setItem("lw_access", data.access_token);
  localStorage.setItem("lw_refresh", data.refresh_token);
  localStorage.setItem("lw_user", JSON.stringify({username:data.username, role:data.role, user_id:data.user_id}));
}
function loggedOut(){
  show($("links"), false);
  show($("login-form"), true);
  show($("workspace"), false);
}
function loggedIn(){
  show($("links"), true);
  show($("login-form"), false);
  show($("workspace"), true);
}
async function api(path, opt) {
  opt = opt || {};
  const headers = Object.assign({"Content-Type":"application/json"}, opt.headers||{});
  if (token()) headers.Authorization = "Bearer "+token();
  const res = await fetch(path, Object.assign({}, opt, {headers}));
  if (res.status === 401) { localStorage.removeItem("lw_access"); throw new Error("login"); }
  if (!res.ok) {
    let d = res.statusText;
    try { const j = await res.json(); d = j.detail || JSON.stringify(j); } catch (e) {}
    throw new Error(typeof d === "string" ? d : JSON.stringify(d));
  }
  if (res.status === 204) return null;
  return res.json();
}
function labInputs(values, prefix){
  const labels = {name:"Name", code:"Code", department:"Department", building:"Building", floor:"Floor", room:"Room", capacity:"Capacity", incharge:"In-charge", phone:"Phone", email:"Email", description:"Notes"};
  return LAB_KEYS.map(function(k){
    return "<input name='"+prefix+k+"' placeholder='"+labels[k]+"' "+(k==="capacity"?"type='number' min='0'":"")+" value='"+esc(values[k]||"")+"'/>";
  }).join("");
}
function labBody(form, prefix){
  const body = {};
  LAB_KEYS.forEach(function(k){
    const node = form.querySelector("[name='"+prefix+k+"']");
    const v = node ? node.value : "";
    body[k] = k==="capacity" ? Number(v||0) : v;
  });
  return body;
}
$("login-form").onsubmit = async function(e){
  e.preventDefault();
  $("le").textContent = "";
  try {
    const data = await api("/api/auth/login", {method:"POST", body: JSON.stringify({username: this.username.value, password: this.password.value})});
    saveSession(data);
    location.reload();
  } catch (err) {
    $("le").textContent = err.message === "login" ? "Invalid credentials" : err.message;
  }
};
$("signout").onclick = function(e){ e.preventDefault(); localStorage.clear(); location.href="/"; };

async function renderLabs(){
  const root = $("workspace");
  root.innerHTML = "<p class='muted'>Loading labs…</p>";
  try {
    const pack = await Promise.all([api("/api/labs"), api("/api/machines")]);
    const labs = pack[0], machines = pack[1];
    root.innerHTML = "<h1>Labs</h1><p class='muted'>Every lab field is editable. Save writes all parameters.</p>";
    const create = document.createElement("form");
    create.className = "card";
    create.innerHTML = "<h3>Add lab</h3><div class='grid'>"+labInputs({},"c_")+"</div><button style='margin-top:10px'>Create lab</button>";
    create.onsubmit = async function(e){ e.preventDefault(); await api("/api/labs",{method:"POST", body:JSON.stringify(labBody(create,"c_"))}); renderLabs(); };
    root.appendChild(create);
    labs.forEach(function(lab){
      const card = document.createElement("form");
      card.className = "card";
      card.innerHTML = "<div class='row'><strong>"+esc(lab.name)+"</strong><span class='muted'>"+(lab.online_count||0)+"/"+(lab.machine_count||0)+" online</span>"+(lab.protected?"<span class='badge'>Protected</span>":"")+"</div><div class='grid' style='margin-top:10px'>"+labInputs(lab,"")+"</div><div class='row' style='margin-top:10px'><button type='submit' class='sec'>Save all fields</button>"+(lab.protected?"":"<button type='button' class='danger del'>Delete lab</button>")+"</div>";
      if (lab.protected && card.querySelector("[name=name]")) card.querySelector("[name=name]").disabled = true;
      card.onsubmit = async function(e){ e.preventDefault(); await api("/api/labs/"+lab.id,{method:"PATCH", body:JSON.stringify(labBody(card,""))}); renderLabs(); };
      var del = card.querySelector(".del");
      if (del) del.onclick = async function(){ if(!confirm("Delete "+lab.name+"?")) return; await api("/api/labs/"+lab.id,{method:"DELETE"}); renderLabs(); };
      root.appendChild(card);
    });
    var html = "<div class='card'><h3>Machines</h3><table><thead><tr><th>Host</th><th>Display name</th><th>Lab</th><th></th></tr></thead><tbody>";
    machines.forEach(function(m){
      var opts = "<option value=''>Unassigned</option>" + labs.map(function(l){ return "<option value='"+l.id+"'"+(m.lab_id===l.id?" selected":"")+">"+esc(l.name)+"</option>"; }).join("");
      html += "<tr data-id='"+m.id+"'><td>"+esc(m.hostname)+"</td><td><input value='"+esc(m.display_name||"")+"'/></td><td><select>"+opts+"</select></td><td><button type='button' class='sec save-m'>Save</button></td></tr>";
    });
    html += "</tbody></table></div>";
    const wrap = document.createElement("div");
    wrap.innerHTML = html;
    wrap.querySelectorAll(".save-m").forEach(function(btn){
      btn.onclick = async function(){
        const tr = btn.closest("tr");
        await api("/api/machines/"+tr.getAttribute("data-id"),{method:"PATCH", body:JSON.stringify({display_name:tr.querySelector("input").value, lab_id:tr.querySelector("select").value||null})});
        renderLabs();
      };
    });
    root.appendChild(wrap);
  } catch (e) {
    if (e.message === "login") { loggedOut(); $("le").textContent = "Please sign in"; return; }
    root.innerHTML = "<div class='card'><h1>Could not load labs</h1><p class='err'>"+esc(e.message)+"</p><p class='muted'>This is usually a database schema mismatch. On the server check: curl -sS http://127.0.0.1/health</p></div>";
  }
}
async function renderUpdates(){
  const root = $("workspace");
  root.innerHTML = "<h1>Updates</h1><p class='muted'>GitHub releases. Pick a tag to shift this server.</p>";
  try {
    const data = await api("/api/admin/updates");
    var html = "<div class='card'><p><span class='badge'>Current "+esc(data.current && data.current.tag)+"</span> <span class='badge'>Latest "+esc(data.latest && data.latest.tag)+"</span></p></div>";
    (data.builds||[]).forEach(function(b){
      html += "<div class='card'><strong>"+esc(b.tag)+"</strong> "+(b.is_current?"<span class='badge'>Current</span> ":"")+(b.is_latest?"<span class='badge'>Latest</span>":"")+"<div class='muted'>"+esc(b.name||"")+"</div><button class='sec apply' data-tag='"+esc(b.tag)+"'>"+(b.action==="downgrade"?"Downgrade": b.action==="current"?"Reinstall":"Update")+"</button></div>";
    });
    if (!(data.builds||[]).length) html += "<p class='muted'>GitHub list empty. Login proxy.cgi then refresh.</p>";
    if (data.status && data.status.message) html += "<p>"+esc(data.status.message)+"</p>";
    root.innerHTML += html;
    root.querySelectorAll(".apply").forEach(function(btn){
      btn.onclick = async function(){ if(!confirm("Apply "+btn.getAttribute("data-tag")+"?")) return; await api("/api/admin/updates/apply",{method:"POST", body:JSON.stringify({tag:btn.getAttribute("data-tag")})}); renderUpdates(); };
    });
  } catch (e) {
    if (e.message === "login") { loggedOut(); return; }
    root.innerHTML += "<p class='err'>"+esc(e.message)+"</p>";
  }
}
async function renderAdmin(){
  const root = $("workspace");
  root.innerHTML = "<p class='muted'>Loading users…</p>";
  try {
    const users = await api("/api/admin/users");
    root.innerHTML = "<h1>Users</h1>";
    const create = document.createElement("form");
    create.className = "card grid";
    create.innerHTML = "<input name='username' placeholder='username' required/><input name='email' placeholder='email' required/><input name='password' type='password' placeholder='password' minlength='8' required/><select name='role'><option>VIEWER</option><option>OPERATOR</option><option>ADMIN</option></select><button>Create</button>";
    create.onsubmit = async function(e){ e.preventDefault(); await api("/api/admin/users",{method:"POST", body:JSON.stringify(Object.fromEntries(new FormData(create)))}); renderAdmin(); };
    root.appendChild(create);
    users.forEach(function(u){
      const card = document.createElement("form");
      card.className = "card grid";
      card.innerHTML = "<input name='username' value='"+esc(u.username)+"'/><input name='email' value='"+esc(u.email)+"'/><input name='full_name' value='"+esc(u.full_name||"")+"'/><select name='role'><option "+(u.role==="ADMIN"?"selected":"")+">ADMIN</option><option "+(u.role==="OPERATOR"?"selected":"")+">OPERATOR</option><option "+(u.role==="VIEWER"?"selected":"")+">VIEWER</option></select><input name='password' type='password' placeholder='new password'/><button type='submit' class='sec'>Save</button><button type='button' class='danger del'>Delete</button>";
      card.onsubmit = async function(e){ e.preventDefault(); const body=Object.fromEntries(new FormData(card)); if(!body.password) delete body.password; await api("/api/admin/users/"+u.id,{method:"PATCH", body:JSON.stringify(body)}); renderAdmin(); };
      card.querySelector(".del").onclick = async function(){ if(!confirm("Delete "+u.username+"?")) return; await api("/api/admin/users/"+u.id,{method:"DELETE"}); renderAdmin(); };
      root.appendChild(card);
    });
  } catch (e) {
    if (e.message === "login") { loggedOut(); return; }
    root.innerHTML = "<p class='err'>"+esc(e.message)+"</p>";
  }
}

fetch("/health").then(function(r){ return r.json(); }).then(function(h){
  if (h.database && h.database !== "ok") banner("Database: "+h.database);
  else if (h.lab_missing_columns && h.lab_missing_columns.length) banner("Lab schema missing columns: "+h.lab_missing_columns.join(", "));
}).catch(function(){ banner("Could not reach /health"); });

if (!token()) loggedOut();
else {
  loggedIn();
  if (PAGE === "updates") renderUpdates();
  else if (PAGE === "admin") renderAdmin();
  else renderLabs();
}
</script>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse)
@router.get("/app", response_class=HTMLResponse)
@router.get("/admin", response_class=HTMLResponse)
@router.get("/infra", response_class=HTMLResponse)
@router.get("/updates", response_class=HTMLResponse)
async def ui_page():
    return HTMLResponse(PAGE)
