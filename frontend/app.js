/* DefectIQ · NTT DATA - single page app */
const State = {
  token: localStorage.getItem("dm_token") || null,
  user: null, perms: [],
  page: 1, pageSize: 25, sort: "last_updated", order: "desc", totalPages: 1,
};
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

/* ----------------------------- API ----------------------------- */
async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (State.token) headers["Authorization"] = "Bearer " + State.token;
  if (opts.body && !(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) { logout(); throw new Error("Session expired"); }
  if (!res.ok) { let m = res.statusText; try { m = (await res.json()).detail || m; } catch (e) {} throw new Error(m); }
  return res;
}
const apiJSON = async (p, o) => (await api(p, o)).json();
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden"); setTimeout(() => t.classList.add("hidden"), 2600); }
function esc(s) { return (s == null ? "" : String(s)).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

/* ----------------------------- Auth ----------------------------- */
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault(); $("#login-error").textContent = "";
  try {
    const data = await apiJSON("/api/login", { method: "POST", body: JSON.stringify({ username: $("#username").value, password: $("#password").value }) });
    State.token = data.token; State.user = data.user; State.perms = data.permissions;
    localStorage.setItem("dm_token", data.token); startApp();
  } catch (err) { $("#login-error").textContent = err.message; }
});
function logout() { State.token = null; localStorage.removeItem("dm_token"); $("#app").classList.add("hidden"); $("#login").classList.remove("hidden"); }
$("#btn-logout").addEventListener("click", logout);
function applyPermissions() {
  const can = (p) => State.perms.includes(p);
  $$(".perm-create").forEach((el) => el.classList.toggle("perm-hide", !can("create")));
  $$(".perm-download").forEach((el) => el.classList.toggle("perm-hide", !can("download")));
  $("#nav-audit").classList.toggle("perm-hide", !can("admin"));
}
async function startApp() {
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  if (!State.user) { const me = await apiJSON("/api/me"); State.user = me.user; State.perms = me.permissions; }
  $("#user-name").textContent = State.user.name;
  $("#user-role").textContent = State.user.role;
  applyPermissions(); initChat(); switchView("dashboard"); loadDashboard();
}

/* ----------------------------- Nav (top tabs) ----------------------------- */
$$(".tab").forEach((el) => el.addEventListener("click", () => switchView(el.dataset.view)));
function switchView(view) {
  $$(".tab").forEach((n) => n.classList.toggle("active", n.dataset.view === view));
  $$(".view").forEach((v) => v.classList.add("hidden"));
  $("#view-" + view).classList.remove("hidden");
  if (view === "defects") loadDefects();
  if (view === "audit") loadAudit();
}

/* ----------------------------- Refresh / Report ----------------------------- */
$("#btn-refresh").addEventListener("click", async () => {
  try { toast("Refreshing from workbook…"); await apiJSON("/api/refresh", { method: "POST" }); toast("Data refreshed"); loadDashboard(); if (!$("#view-defects").classList.contains("hidden")) loadDefects(); }
  catch (e) { toast(e.message); }
});
$("#btn-report").addEventListener("click", () => fetchDownload("/api/export/consolidated"));
function setFreshness(k) { $("#freshness").textContent = "Data as of: " + (k.last_refreshed || k.reconciled_at || "—"); }

/* ----------------------------- Dashboard ----------------------------- */
const KPI_DEFS = [
  ["total_in_smartsheet", "Total in Smartsheet", "k-ss"],
  ["issue_statuses_count", "Issue Statuses", "k-iss"],
  ["matched_defects", "Matched Defects", "k-matched"],
  ["missing_in_github", "Missing in GitHub", "k-missing"],
  ["linked_to_github", "Linked to GitHub", "k-linked"],
  ["not_linked_to_github", "Not Linked to GitHub", "k-notlinked"],
];
const KPI_STATUS = [
  ["open_defects", "Open", "k-open"],
  ["in_progress", "In Progress", "k-progress"],
  ["closed_defects", "Closed", "k-closed"],
  ["unassigned_defects", "Unassigned", "k-unassigned"],
];
const PLOT_CFG = { displayModeBar: false, responsive: true };
const PAL = ["#0a66c2", "#17a673", "#e0a800", "#d9534f", "#6f42c1", "#0b1f3a", "#00b2a9", "#fd7e14", "#20c997", "#8e44ad"];
const EMPTY_LABELS = ["(none)", "unspecified", "unknown", "(unassigned)", "n/a", ""];
const isEmptyLabel = (lbl) => EMPTY_LABELS.includes(String(lbl ?? "").trim().toLowerCase());
let chartData = null;
async function loadDashboard() {
  const k = await apiJSON("/api/kpis"); setFreshness(k);
  const card = ([key, label, cls], val) => `<div class="kpi ${cls}"><div class="num">${val ?? k[key] ?? 0}</div><div class="lbl">${label}</div></div>`;
  $("#kpi-cards").innerHTML = KPI_DEFS.map((d) => card(d)).join("");
  $("#kpi-status").innerHTML = KPI_STATUS.map((d) => card(d)).join("");
  chartData = await apiJSON("/api/charts");
  renderCharts();
}
function renderCharts() {
  const c = chartData; if (!c) return;
  const showEmpty = $("#toggle-empty").checked;
  const L = { margin: { t: 10, r: 10, b: 40, l: 40 }, font: { size: 11 }, showlegend: false };
  const clean = (a) => (showEmpty ? a : (a || []).filter((x) => !isEmptyLabel(x[0])));
  const pairs = (a) => { const f = clean(a); return { labels: f.map((x) => x[0]), values: f.map((x) => x[1]) }; };
  const colors = (n) => Array.from({ length: n }, (_, i) => PAL[i % PAL.length]);
  let d = pairs(c.status_distribution);
  Plotly.newPlot("chart-status", [{ type: "pie", labels: d.labels, values: d.values, hole: .5, marker: { colors: PAL } }], { ...L, showlegend: true }, PLOT_CFG);
  d = pairs(c.issue_source_distribution);
  Plotly.newPlot("chart-issuesource", [{ type: "bar", x: d.labels, y: d.values, marker: { color: colors(d.labels.length) } }], { ...L, margin: { t: 10, r: 10, b: 70, l: 40 } }, PLOT_CFG);
  d = pairs(c.source_comparison);
  Plotly.newPlot("chart-source", [{ type: "pie", labels: d.labels, values: d.values, marker: { colors: ["#0a66c2", "#e0a800"] } }], { ...L, showlegend: true }, PLOT_CFG);
  d = pairs(c.priority_distribution);
  Plotly.newPlot("chart-priority", [{ type: "bar", x: d.labels, y: d.values, marker: { color: colors(d.labels.length) } }], L, PLOT_CFG);
  d = pairs(c.validation_distribution);
  Plotly.newPlot("chart-validation", [{ type: "pie", labels: d.labels, values: d.values, marker: { colors: PAL } }], { ...L, showlegend: true }, PLOT_CFG);
  d = pairs(c.developer_distribution);
  const owner = (s) => esc(String(s || "").replace(/[-_ ]?contractor_cel$/i, "").replace(/_cel$/i, "").replace(/[-_]/g, " ").trim());
  const ownerNames = d.labels.map(owner);
  Plotly.newPlot("chart-dev", [
    { type: "bar", orientation: "h", y: ownerNames.slice().reverse(), x: d.values.slice().reverse(), marker: { color: colors(d.labels.length).reverse() }, hovertemplate: "%{y}: %{x}<extra></extra>" },
  ], { ...L, margin: { t: 10, r: 10, b: 30, l: 10 }, xaxis: { gridcolor: "#eef2f7", zeroline: false }, yaxis: { automargin: true } }, PLOT_CFG);
  d = pairs(c.module_distribution);
  Plotly.newPlot("chart-module", [{ type: "bar", x: d.labels, y: d.values, marker: { color: colors(d.labels.length) } }], { ...L, margin: { t: 10, r: 10, b: 90, l: 40 } }, PLOT_CFG);
}
document.addEventListener("change", (e) => { if (e.target && e.target.id === "toggle-empty") renderCharts(); });

/* ----------------------------- Defects ----------------------------- */
function statusPill(s) { const cls = { "Open": "p-open", "In Progress": "p-inprogress", "Closed": "p-closed" }[s] || "p-unknown"; return `<span class="pill ${cls}">${s || "—"}</span>`; }
function filterParams() {
  const p = new URLSearchParams(); const add = (k, v) => { if (v) p.set(k, v); };
  add("search", $("#f-search").value); add("status", $("#f-status").value); add("source", $("#f-source").value);
  add("validation", $("#f-validation").value); add("developer", $("#f-developer").value); add("priority", $("#f-priority").value);
  p.set("sort", State.sort); p.set("order", State.order); return p;
}
async function loadDefects() {
  const p = filterParams(); p.set("page", State.page); p.set("page_size", State.pageSize);
  const data = await apiJSON("/api/defects?" + p.toString());
  State.totalPages = data.pages || 1;
  const canU = State.perms.includes("update"), canD = State.perms.includes("delete");
  $("#defect-tbody").innerHTML = data.items.map((d) => `
    <tr data-id="${d.record_id}">
      <td>${esc(d.customer_defect_id)}</td>
      <td>${d.github_url ? `<a href="${d.github_url}" target="_blank">#${esc(d.github_issue_id)}</a>` : esc(d.github_issue_id)}</td>
      <td title="${esc(d.defect_title)}">${esc(d.defect_title)}</td>
      <td>${esc(d.customer_status)}</td><td>${esc(d.github_status)}</td>
      <td>${statusPill(d.consolidated_status)}</td>
      <td>${esc(d.assigned_developer)}</td><td>${esc(d.priority)}</td>
      <td>${esc(d.issue_source)}</td>
      <td><span class="tag">${d.source_availability === "Both" ? "Linked" : "Not linked"}</span></td>
      <td class="row-actions">
        <button class="btn" data-act="view">View</button>
        ${canU ? `<button class="btn" data-act="edit">Edit</button>` : ""}
        ${canD ? `<button class="btn btn-danger" data-act="del">Del</button>` : ""}
      </td></tr>`).join("") || `<tr><td colspan="11" style="text-align:center;padding:30px" class="muted">No defects match your filters.</td></tr>`;
  $("#pg-info").textContent = `Page ${data.page} of ${data.pages} · ${data.total} defects`;
  $("#pg-prev").disabled = data.page <= 1; $("#pg-next").disabled = data.page >= data.pages;
}
$("#defect-tbody").addEventListener("click", (e) => {
  const btn = e.target.closest("button"); const tr = e.target.closest("tr"); if (!tr) return;
  const id = tr.dataset.id;
  if (!btn) { openDetail(id); return; }
  const a = btn.dataset.act;
  if (a === "view") openDetail(id); else if (a === "edit") openForm(id); else if (a === "del") deleteDefect(id);
});
$("#btn-apply").addEventListener("click", () => { State.page = 1; loadDefects(); });
$("#f-search").addEventListener("keydown", (e) => { if (e.key === "Enter") { State.page = 1; loadDefects(); } });
$("#pg-prev").addEventListener("click", () => { if (State.page > 1) { State.page--; loadDefects(); } });
$("#pg-next").addEventListener("click", () => { if (State.page < State.totalPages) { State.page++; loadDefects(); } });
$$("#defect-table th[data-sort]").forEach((th) => th.addEventListener("click", () => {
  const col = th.dataset.sort;
  if (State.sort === col) State.order = State.order === "asc" ? "desc" : "asc"; else { State.sort = col; State.order = "asc"; }
  loadDefects();
}));

/* ----------------------------- Detail + CRUD ----------------------------- */
function closeModal() { $("#modal").classList.add("hidden"); }
$("#modal-close").addEventListener("click", closeModal);
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
async function openDetail(id) {
  const d = await apiJSON("/api/defects/" + encodeURIComponent(id));
  $("#modal-title").textContent = d.defect_title || d.record_id;
  const rows = [["Customer Defect ID", d.customer_defect_id], ["GitHub Issue ID", d.github_issue_id], ["Consolidated Status", d.consolidated_status],
    ["Customer Status", d.customer_status], ["GitHub Status", d.github_status], ["Assigned Owner", d.assigned_developer], ["Priority", d.priority],
    ["Issue Source", d.issue_source], ["Module", d.module], ["NTT Category", d.ntt_category], ["Link", d.source_availability === "Both" ? "Linked to GitHub" : "Not linked"],
    ["Data Validation", d.data_validation_status], ["Created", d.created_date], ["Last Updated", d.last_updated],
    ["Development Progress", d.development_progress], ["Latest Comment", d.latest_comment], ["Description", d.description]];
  $("#modal-body").innerHTML = rows.map(([k, v]) => `<div class="detail-row"><div class="k">${k}</div><div>${esc(v) || "—"}</div></div>`).join("") +
    (d.github_url ? `<div style="margin-top:14px"><a class="btn" href="${d.github_url}" target="_blank">Open in GitHub ↗</a></div>` : "");
  $("#modal").classList.remove("hidden");
}
const STATUS_OPTS = ["Open", "In Progress", "Closed", "Unknown"];
async function openForm(id) {
  let d = { consolidated_status: "Open" }; if (id) d = await apiJSON("/api/defects/" + encodeURIComponent(id));
  $("#modal-title").textContent = id ? "Edit defect" : "New defect";
  const opt = (v) => STATUS_OPTS.map((s) => `<option ${s === v ? "selected" : ""}>${s}</option>`).join("");
  $("#modal-body").innerHTML = `
    <div class="form-grid">
      <div><label>Customer Defect ID</label><input id="in-cust" value="${esc(d.customer_defect_id)}"/></div>
      <div><label>GitHub Issue ID</label><input id="in-gh" value="${esc(d.github_issue_id)}"/></div>
      <div class="full"><label>Title</label><input id="in-title" value="${esc(d.defect_title)}"/></div>
      <div><label>Status</label><select id="in-status">${opt(d.consolidated_status)}</select></div>
      <div><label>Priority</label><input id="in-prio" value="${esc(d.priority)}"/></div>
      <div><label>Assigned Owner</label><input id="in-dev" value="${esc(d.assigned_developer)}"/></div>
      <div><label>Module</label><input id="in-mod" value="${esc(d.module)}"/></div>
      <div class="full"><label>Description</label><textarea id="in-desc" rows="3">${esc(d.description)}</textarea></div>
    </div>
    <div class="modal-actions"><button class="btn" id="form-cancel">Cancel</button><button class="btn btn-primary" id="form-save">${id ? "Save changes" : "Create defect"}</button></div>`;
  $("#modal").classList.remove("hidden");
  $("#form-cancel").addEventListener("click", closeModal);
  $("#form-save").addEventListener("click", () => saveForm(id));
}
async function saveForm(id) {
  const body = { customer_defect_id: $("#in-cust").value || null, github_issue_id: $("#in-gh").value || null, defect_title: $("#in-title").value,
    consolidated_status: $("#in-status").value, priority: $("#in-prio").value || null, assigned_developer: $("#in-dev").value || null,
    module: $("#in-mod").value || null, description: $("#in-desc").value || null };
  try {
    if (id) await apiJSON("/api/defects/" + encodeURIComponent(id), { method: "PUT", body: JSON.stringify(body) });
    else await apiJSON("/api/defects", { method: "POST", body: JSON.stringify(body) });
    closeModal(); toast(id ? "Defect updated" : "Defect created"); loadDefects(); loadDashboard();
  } catch (e) { toast(e.message); }
}
async function deleteDefect(id) {
  if (!confirm("Delete this defect record? This is logged in the audit trail.")) return;
  try { await apiJSON("/api/defects/" + encodeURIComponent(id), { method: "DELETE" }); toast("Defect deleted"); loadDefects(); loadDashboard(); }
  catch (e) { toast(e.message); }
}
$("#btn-new").addEventListener("click", () => openForm(null));

/* ----------------------------- Export ----------------------------- */
$("#btn-export").addEventListener("click", (e) => { e.stopPropagation(); e.currentTarget.parentElement.classList.toggle("open"); });
document.addEventListener("click", () => $$(".dropdown").forEach((d) => d.classList.remove("open")));
async function fetchDownload(url) {
  try {
    const res = await api(url); const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || ""; const m = cd.match(/filename="(.+?)"/);
    const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = m ? m[1] : "export.xlsx"; link.click(); URL.revokeObjectURL(link.href);
  } catch (e) { toast(e.message); }
}
$("#exp-filtered").addEventListener("click", () => fetchDownload("/api/export/filtered?" + filterParams().toString()));
$("#exp-consolidated").addEventListener("click", () => fetchDownload("/api/export/consolidated"));
$("#exp-kpi").addEventListener("click", () => fetchDownload("/api/export/kpis"));
$("#exp-github").addEventListener("click", () => fetchDownload("/api/export/source/github"));
$("#exp-smartsheet").addEventListener("click", () => fetchDownload("/api/export/source/smartsheet"));
$("#exp-issues").addEventListener("click", () => fetchDownload("/api/export/source/issue-statuses"));

/* ----------------------------- Chat (docked, visual-first, interactive) ----------------------------- */
const SUGGESTIONS = ["Defect summary", "How many are open?", "Owner-wise distribution", "By issue source", "Unassigned defects", "Any duplicates?"];
const LIST_TOOLS = ["list_defects", "unassigned_defects", "reconciliation_gaps", "search_defects", "defect_detail"];
let chatHistory = [], chatInit = false, chartSeq = 0;
function initChat() {
  if (chatInit) return; chatInit = true;
  $("#chat-suggestions").innerHTML = SUGGESTIONS.map((s) => `<button>${s}</button>`).join("");
  $$("#chat-suggestions button").forEach((b) => b.addEventListener("click", () => { $("#chat-text").value = b.textContent; sendChat(); }));
  addBotMessage("Hi! I'm DefectIQ. Ask about defect counts, statuses, owners, issue sources, reconciliation gaps, or a specific defect.", null);
}
$("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); sendChat(); });
$("#btn-clear-chat").addEventListener("click", () => {
  chatHistory = []; $("#chat-log").innerHTML = "";
  addBotMessage("Conversation cleared. Ask me anything about the defects.", null);
});
function addUserMessage(text) { const el = document.createElement("div"); el.className = "msg user"; el.textContent = text; $("#chat-log").appendChild(el); $("#chat-log").scrollTop = 1e9; }

function statRow(items) {
  return `<div class="stat-row">${items.map(([l, n]) => `<div class="stat"><div class="n">${n ?? 0}</div><div class="l">${esc(l)}</div></div>`).join("")}</div>`;
}
function miniTable(rows) {
  const r = rows.slice(0, 7);
  const head = `<tr><th>Cust</th><th>GitHub</th><th>Title</th><th>Status</th><th>Owner</th></tr>`;
  const body = r.map((x) => `<tr data-rid="${esc(x.record_id)}"><td>${esc(x.customer_defect_id)}</td><td>${esc(x.github_issue_id)}</td><td title="${esc(x.defect_title)}">${esc((x.defect_title || "").slice(0, 26))}</td><td>${esc(x.consolidated_status)}</td><td>${esc((x.assigned_developer || "").split(";")[0])}</td></tr>`).join("");
  const more = rows.length > 7 ? `<div class="more">+ ${rows.length - 7} more — refine your question to see others</div>` : "";
  return `<table class="mini"><thead>${head}</thead><tbody>${body}</tbody></table>${more}`;
}
function buildVisual(data) {
  if (!data) return { html: "", charts: [] };
  const rows = data.rows || [], extra = data.extra || {}, tool = data.tool || (data.meta && data.meta.tool);
  const charts = []; let html = "";
  const chart = (spec) => { const id = "mc" + (++chartSeq); charts.push({ id, ...spec }); return `<div id="${id}" class="mini-chart"></div>`; };
  if (tool === "summary" && extra.total_defects != null) {
    html += statRow([["Total", extra.total_defects], ["Open", extra.open_defects], ["In Prog", extra.in_progress], ["Closed", extra.closed_defects]]);
    html += chart({ labels: ["Open", "In Progress", "Closed"], values: [extra.open_defects, extra.in_progress, extra.closed_defects], orient: "v" });
  } else if (rows[0] && "count" in rows[0]) {
    // Any distribution: developer_distribution ({developer,count}) or defect_distribution ({label,count})
    const key = Object.keys(rows[0]).find((x) => x !== "count") || "label";
    const r = rows.slice(0, 10);
    html += chart({ labels: r.map((x) => x[key]), values: r.map((x) => x.count), orient: "h" });
  } else if (tool === "count_defects") {
    const a = data.args || {};
    const lbl = a.status || a.source || a.developer || a.priority || "Defects";
    html += statRow([[lbl, data.count]]);
  } else if (rows.length && (tool ? LIST_TOOLS.includes(tool) : rows[0].defect_title !== undefined)) {
    html += miniTable(rows);
  } else if (data.count != null && data.count > 0) {
    html += statRow([["Result", data.count]]);
  }
  return { html, charts };
}
function addBotMessage(text, data) {
  const el = document.createElement("div"); el.className = "msg bot";
  const vis = buildVisual(data);
  el.innerHTML = `<div class="headline">${esc(text)}</div>` + vis.html;
  $("#chat-log").appendChild(el); $("#chat-log").scrollTop = 1e9;
  vis.charts.forEach((c) => {
    const horiz = c.orient === "h";
    const cols = c.labels.map((_, i) => PAL[i % PAL.length]);
    const trace = horiz
      ? { type: "bar", orientation: "h", y: c.labels.slice().reverse(), x: c.values.slice().reverse(), marker: { color: cols.slice().reverse() } }
      : { type: "bar", x: c.labels, y: c.values, marker: { color: cols } };
    Plotly.newPlot(c.id, [trace], { margin: horiz ? { t: 6, r: 6, b: 24, l: 120 } : { t: 6, r: 6, b: 30, l: 34 }, font: { size: 10 }, height: 200 }, PLOT_CFG);
  });
  el.querySelectorAll("table.mini tbody tr").forEach((tr) => tr.addEventListener("click", () => { if (tr.dataset.rid) openDetail(tr.dataset.rid); }));
}
async function sendChat() {
  const text = $("#chat-text").value.trim(); if (!text) return;
  $("#chat-text").value = ""; addUserMessage(text); chatHistory.push({ role: "user", content: text });
  const thinking = document.createElement("div"); thinking.className = "msg bot"; thinking.textContent = "…"; $("#chat-log").appendChild(thinking);
  try {
    const resp = await apiJSON("/api/chat", { method: "POST", body: JSON.stringify({ message: text, history: chatHistory.slice(-8) }) });
    thinking.remove(); addBotMessage(resp.reply, resp.data); chatHistory.push({ role: "assistant", content: resp.reply });
  } catch (e) { thinking.remove(); addBotMessage("Sorry, I hit an error: " + e.message, null); }
}

/* ----------------------------- Audit ----------------------------- */
async function loadAudit() {
  try {
    const data = await apiJSON("/api/audit");
    $("#audit-tbody").innerHTML = data.entries.map((e) => `<tr><td>${esc(e.ts)}</td><td>${esc(e.user)}</td><td>${esc(e.action)}</td><td>${esc(e.record_id)}</td><td>${esc(JSON.stringify(e.details))}</td></tr>`).join("")
      || `<tr><td colspan="5" class="muted" style="text-align:center;padding:20px">No audit entries yet.</td></tr>`;
  } catch (e) { toast(e.message); }
}

/* ----------------------------- Boot ----------------------------- */
if (State.token) startApp().catch(() => logout());
