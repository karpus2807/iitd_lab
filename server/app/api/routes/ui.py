"""Management UI served by the API (Labs + Updates). Works with an old Nginx SPA image."""

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
    input, select { background:#1b2530; border:1px solid var(--line); color:var(--text); border-radius:8px; padding:8px; min-width:0; }
    button { background:var(--accent); color:#062018; border:0; border-radius:8px; padding:8px 12px; font-weight:600; cursor:pointer; }
    button.sec { background:#1b2530; color:var(--text); border:1px solid var(--line); }
    button.danger { background:var(--crit); color:#fff; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:8px; }
    .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
    .err { color:var(--crit); }
    .badge { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:2px 8px; font-size:12px; }
    table { width:100%; border-collapse:collapse; font-size:14px; }
    th, td { text-align:left; padding:8px; border-bottom:1px solid var(--line); vertical-align:top; }
    .login { max-width:380px; margin:10vh auto; }
  </style>
</head>
<body>
<header id="nav"></header>
<main id="root"><p class="muted">Loading…</p></main>
<script>
const PAGE = location.pathname.includes("/updates") ? "updates" : location.pathname.includes("/admin") ? "admin" : "labs";
const LAB_KEYS = ["name","code","department","building","floor","room","capacity","incharge","phone","email","description"];
function esc(s){ return String(s??"").replace(/[&<>"'`]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','`':'&#96;'}[c])); }
function el(html){ const d=document.createElement("div"); d.innerHTML=html.trim(); return d.firstElementChild; }
function token(){ return localStorage.getItem("lw_access"); }
function saveSession(data){
  localStorage.setItem("lw_access", data.access_token);
  localStorage.setItem("lw_refresh", data.refresh_token);
  localStorage.setItem("lw_user", JSON.stringify({username:data.username, role:data.role, user_id:data.user_id}));
}
function nav(){
  const n=document.getElementById("nav");
  n.innerHTML = "<strong>LabWatch</strong> <a href='/labs' id='n-labs'>Labs</a> <a href='/updates' id='n-updates'>Updates</a> <a href='/api/ui/admin' id='n-admin'>Users</a> <a href='/machines'>Machines</a> <a href='#' id='out'>Sign out</a>";
  var active = document.getElementById("n-"+PAGE);
  if (active) active.classList.add("active");
  document.getElementById("out").onclick=function(e){ e.preventDefault(); localStorage.clear(); location.href="/"; };
}
async function api(path, opt) {
  opt = opt || {};
  const headers = Object.assign({"Content-Type":"application/json"}, opt.headers||{});
  if (token()) headers.Authorization = "Bearer "+token();
  const res = await fetch(path, Object.assign({}, opt, {headers}));
  if (res.status === 401) { localStorage.removeItem("lw_access"); throw new Error("login"); }
  if (!res.ok) {
    let d = res.statusText;
    try { const j = await res.json(); d = j.detail || JSON.stringify(j); } catch(e) {}
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
    const v = form.querySelector("[name='"+prefix+k+"']").value;
    body[k] = k==="capacity" ? Number(v||0) : v;
  });
  return body;
}
function renderLogin(msg){
  document.getElementById("nav").innerHTML = "<strong>LabWatch</strong>";
  const root=document.getElementById("root");
  root.innerHTML="";
  const box=el("<form class='card login'><h1>Sign in</h1><p class='muted'>Labs editor and Updates</p><div class='grid' style='grid-template-columns:1fr'><input name='username' placeholder='Username' value='admin'/><input name='password' type='password' placeholder='Password'/></div><p class='err' id='le'></p><button style='margin-top:12px'>Sign in</button></form>");
  box.onsubmit=async function(e){
    e.preventDefault();
    try {
      const data=await api("/api/auth/login",{method:"POST", body:JSON.stringify({username:box.username.value, password:box.password.value})});
      saveSession(data);
      location.reload();
    } catch(err){
      var le = box.querySelector("#le");
      if (le) le.textContent = err.message==="login" ? "Invalid credentials" : err.message;
    }
  };
  root.append(box);
  var le0 = box.querySelector("#le");
  if (le0 && msg) le0.textContent = msg;
}
async function renderLabs(){
  const root=document.getElementById("root");
  try {
    const pack = await Promise.all([api("/api/labs"), api("/api/machines")]);
    const labs = pack[0], machines = pack[1];
    root.innerHTML="";
    root.append(el("<h1>Labs</h1>"));
    root.append(el("<p class='muted'>Every lab field is editable. Save writes all parameters. Delete moves hosts to Unassigned.</p>"));
    const create=el("<form class='card'><h3>Add lab</h3><div class='grid'>"+labInputs({},"c_")+"</div><button style='margin-top:10px'>Create lab</button></form>");
    create.onsubmit=async function(e){ e.preventDefault(); await api("/api/labs",{method:"POST", body:JSON.stringify(labBody(create,"c_"))}); renderLabs(); };
    root.append(create);
    labs.forEach(function(lab){
      const card=el("<form class='card'><div class='row'><strong>"+esc(lab.name)+"</strong><span class='muted'>"+(lab.online_count||0)+"/"+(lab.machine_count||0)+" online</span>"+(lab.protected?"<span class='badge'>Protected</span>":"")+"</div><div class='grid' style='margin-top:10px'>"+labInputs(lab,"")+"</div><div class='row' style='margin-top:10px'><button type='submit' class='sec'>Save all fields</button>"+(lab.protected?"":"<button type='button' class='danger del'>Delete lab</button>")+"</div></form>");
      if (lab.protected) card.querySelector("[name=name]").disabled = true;
      card.onsubmit=async function(e){ e.preventDefault(); await api("/api/labs/"+lab.id,{method:"PATCH", body:JSON.stringify(labBody(card,""))}); renderLabs(); };
      const del=card.querySelector(".del");
      if (del) del.onclick=async function(){ if(!confirm("Delete "+lab.name+"?")) return; await api("/api/labs/"+lab.id,{method:"DELETE"}); renderLabs(); };
      root.append(card);
    });
    const mt=el("<div class='card'><h3>Machines</h3><table><thead><tr><th>Host</th><th>Display name</th><th>Lab</th><th></th></tr></thead><tbody></tbody></table></div>");
    machines.forEach(function(m){
      const opts=["<option value=''>Unassigned</option>"].concat(labs.map(function(l){ return "<option value='"+l.id+"' "+(m.lab_id===l.id?"selected":"")+">"+esc(l.name)+"</option>"; })).join("");
      const tr=el("<tr><td>"+esc(m.hostname)+"</td><td><input value='"+esc(m.display_name||"")+"'/></td><td><select>"+opts+"</select></td><td><button type='button' class='sec'>Save</button></td></tr>");
      tr.querySelector("button").onclick=async function(){
        await api("/api/machines/"+m.id,{method:"PATCH", body:JSON.stringify({display_name:tr.querySelector("input").value, lab_id:tr.querySelector("select").value||null})});
        renderLabs();
      };
      mt.querySelector("tbody").append(tr);
    });
    root.append(mt);
  } catch (e) {
    if (e.message==="login") return renderLogin();
    root.innerHTML = "<p class='err'>"+esc(e.message)+"</p>";
  }
}
async function renderUpdates(){
  const root=document.getElementById("root");
  root.innerHTML="<h1>Updates</h1><p class='muted'>GitHub releases. Pick a tag to shift this server.</p>";
  try {
    const data=await api("/api/admin/updates");
    const box=el("<div class='card'></div>");
    box.innerHTML="<p><span class='badge'>Current "+esc(data.current && data.current.tag)+"</span> <span class='badge'>Latest "+esc(data.latest && data.latest.tag)+"</span></p>";
    (data.builds||[]).forEach(function(b){
      const row=el("<div class='card'><strong>"+esc(b.tag)+"</strong> "+(b.is_current?"<span class='badge'>Current</span>":"")+" "+(b.is_latest?"<span class='badge'>Latest</span>":"")+"<div class='muted'>"+esc(b.name||"")+"</div><button class='sec'>"+(b.action==="downgrade"?"Downgrade": b.action==="current"?"Reinstall":"Update")+"</button></div>");
      row.querySelector("button").onclick=async function(){ if(!confirm("Apply "+b.tag+"?")) return; await api("/api/admin/updates/apply",{method:"POST", body:JSON.stringify({tag:b.tag})}); renderUpdates(); };
      box.append(row);
    });
    if (!(data.builds||[]).length) box.append(el("<p class='muted'>GitHub list empty. Login proxy.cgi then refresh.</p>"));
    if (data.status && data.status.message) box.append(el("<p>"+esc(data.status.message)+"</p>"));
    root.append(box);
  } catch (e) {
    if (e.message==="login") return renderLogin();
    root.innerHTML += "<p class='err'>"+esc(e.message)+"</p>";
  }
}
async function renderAdmin(){
  const root=document.getElementById("root");
  try {
    const users=await api("/api/admin/users");
    root.innerHTML="";
    root.append(el("<h1>Users</h1>"));
    const create=el("<form class='card grid'><input name='username' placeholder='username' required/><input name='email' placeholder='email' required/><input name='password' type='password' placeholder='password' minlength='8' required/><select name='role'><option>VIEWER</option><option>OPERATOR</option><option>ADMIN</option></select><button>Create</button></form>");
    create.onsubmit=async function(e){ e.preventDefault(); await api("/api/admin/users",{method:"POST", body:JSON.stringify(Object.fromEntries(new FormData(create)))}); renderAdmin(); };
    root.append(create);
    users.forEach(function(u){
      const card=el("<form class='card grid'><input name='username' value='"+esc(u.username)+"'/><input name='email' value='"+esc(u.email)+"'/><input name='full_name' value='"+esc(u.full_name||"")+"'/><select name='role'><option "+(u.role==="ADMIN"?"selected":"")+">ADMIN</option><option "+(u.role==="OPERATOR"?"selected":"")+">OPERATOR</option><option "+(u.role==="VIEWER"?"selected":"")+">VIEWER</option></select><input name='password' type='password' placeholder='new password'/><button type='submit' class='sec'>Save</button><button type='button' class='danger del'>Delete</button></form>");
      card.onsubmit=async function(e){
        e.preventDefault();
        const body=Object.fromEntries(new FormData(card));
        if (!body.password) delete body.password;
        await api("/api/admin/users/"+u.id,{method:"PATCH", body:JSON.stringify(body)});
        renderAdmin();
      };
      card.querySelector(".del").onclick=async function(){ if(!confirm("Delete "+u.username+"?")) return; await api("/api/admin/users/"+u.id,{method:"DELETE"}); renderAdmin(); };
      root.append(card);
    });
  } catch (e) {
    if (e.message==="login") return renderLogin();
    root.innerHTML="<p class='err'>"+esc(e.message)+"</p>";
  }
}
try {
  if (!token()) renderLogin();
  else {
    nav();
    if (PAGE==="updates") renderUpdates();
    else if (PAGE==="admin") renderAdmin();
    else renderLabs();
  }
} catch (e) {
  document.getElementById("root").innerHTML = "<div class='card'><h1>Sign in</h1><p class='err'>"+esc(e.message)+"</p><p class='muted'>Clear site data for this host if this keeps happening.</p></div>";
  renderLogin(e.message);
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
