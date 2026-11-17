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
function logout() { State.token = null; localStorage.removeItem("dm_token"); $("#app").classList.add("hidden"); $("#app").style.display = "none"; $("#login").classList.remove("hidden"); $("#login").style.display = ""; }
$("#btn-logout").addEventListener("click", logout);
function applyPermissions() {
  const can = (p) => State.perms.includes(p);
  $$(".perm-create").forEach((el) => el.classList.toggle("perm-hide", !can("create")));
  $$(".perm-download").forEach((el) => el.classList.toggle("perm-hide", !can("download")));
  $("#nav-audit").classList.toggle("perm-hide", !can("admin"));
}
async function startApp() {
  $("#login").classList.add("hidden"); $("#login").style.display = "none";
  $("#app").classList.remove("hidden"); $("#app").style.display = "";
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
  if (view === "dashboard") {
    if (chartsNeedRender && chartData) {
      renderCharts();
      chartsNeedRender = false;
    } else resizeDashboardCharts();
  }
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
const PLOT_CFG = { displayModeBar: false, responsive: true, scrollZoom: false, doubleClick: false };
const NO_ZOOM_AXES = { dragmode: false, xaxis: { fixedrange: true }, yaxis: { fixedrange: true } };
const PAL = ["#0a66c2", "#17a673", "#e0a800", "#d9534f", "#6f42c1", "#0b1f3a", "#00b2a9", "#fd7e14", "#20c997", "#8e44ad"];
const EMPTY_LABELS = ["(none)", "unspecified", "unknown", "(unassigned)", "n/a", ""];
const isEmptyLabel = (lbl) => EMPTY_LABELS.includes(String(lbl ?? "").trim().toLowerCase());
const normChartKey = (s) => String(s ?? "").trim().toLowerCase().replace(/\s+/g, " ");
const CHART_THEMES = {
  status: {
    order: ["Open", "In Progress", "Closed", "Unknown"],
    colors: { open: "#e0a800", "in progress": "#0a66c2", closed: "#17a673", unknown: "#6b7a90" },
  },
  priority: {
    order: ["Critical/Urgent", "Critical", "High", "Medium", "Low", "Unknown", "(none)"],
    colors: {
      "critical/urgent": "#c0392b",
      critical: "#d9534f",
      high: "#fd7e14",
      medium: "#e0a800",
      low: "#17a673",
      unknown: "#6b7a90",
      "(none)": "#9aa8bc",
      none: "#9aa8bc",
    },
  },
  validation: {
    order: ["Matched", "Missing", "Duplicate", "Requires Review", "Unknown"],
    colors: { matched: "#17a673", missing: "#d9534f", duplicate: "#6f42c1", "requires review": "#e0a800", unknown: "#6b7a90" },
  },
  link: {
    order: ["Linked to GitHub", "Not Linked"],
    colors: { "linked to github": "#17a673", "not linked": "#0a66c2" },
  },
  issueSource: {
    order: ["PROD", "UAT", "SIT", "DEV", "QA", "Exception Triage", "Shared Mailbox", "(none)"],
    colors: {
      prod: "#d9534f",
      uat: "#fd7e14",
      sit: "#0a66c2",
      dev: "#17a673",
      qa: "#6f42c1",
      "exception triage": "#0b1f3a",
      "shared mailbox": "#00b2a9",
      "(none)": "#9aa8bc",
    },
  },
  module: {
    order: [],
    colors: { "(none)": "#9aa8bc", none: "#9aa8bc", others: "#6b7a90" },
  },
};
function colorForLabel(label, theme, fallbackIdx) {
  const k = normChartKey(label);
  if (theme.colors[k]) return theme.colors[k];
  const hit = Object.entries(theme.colors).find(([key]) => k.includes(key) || key.includes(k));
  return hit ? hit[1] : PAL[fallbackIdx % PAL.length];
}
function sortChartSeries(labels, values, theme) {
  const items = labels.map((label, i) => ({ label, value: values[i] }));
  const order = theme.order || [];
  const rank = (label) => {
    const k = normChartKey(label);
    let idx = order.findIndex((o) => normChartKey(o) === k);
    if (idx >= 0) return idx;
    idx = order.findIndex((o) => k.includes(normChartKey(o)) || normChartKey(o).includes(k));
    return idx >= 0 ? idx : order.length + 1;
  };
  items.sort((a, b) => {
    const d = rank(a.label) - rank(b.label);
    return d !== 0 ? d : b.value - a.value;
  });
  return {
    labels: items.map((x) => x.label),
    values: items.map((x) => x.value),
    colors: items.map((x, i) => colorForLabel(x.label, theme, i)),
  };
}
function cleanChartRows(a) {
  const showEmpty = $("#toggle-empty").checked;
  return (showEmpty ? (a || []) : (a || []).filter((x) => !isEmptyLabel(x[0])));
}
function themedPairs(rows, theme) {
  const f = cleanChartRows(rows);
  return sortChartSeries(f.map((x) => x[0]), f.map((x) => x[1]), theme);
}
function moduleChartPairs(rows) {
  const merged = new Map();
  for (const [lbl, val] of cleanChartRows(rows)) {
    const name = normChartKey(lbl) === "all" ? "Others" : String(lbl);
    merged.set(name, (merged.get(name) || 0) + val);
  }
  const labels = [...merged.keys()];
  return sortChartSeries(labels, labels.map((k) => merged.get(k)), CHART_THEMES.module);
}
const DASH_CHART_IDS = ["chart-status", "chart-issuesource", "chart-source", "chart-priority", "chart-validation", "chart-dev", "chart-module"];
let chartData = null, chartsNeedRender = false;
function resizeDashboardCharts() {
  if (typeof Plotly === "undefined") return;
  requestAnimationFrame(() => {
    DASH_CHART_IDS.forEach((id) => {
      const el = document.getElementById(id);
      if (el && el.data) Plotly.Plots.resize(id);
    });
  });
}
async function loadDashboard() {
  const k = await apiJSON("/api/kpis"); setFreshness(k);
  const card = ([key, label, cls], val) => `<div class="kpi ${cls}"><div class="num">${val ?? k[key] ?? 0}</div><div class="lbl">${label}</div></div>`;
  $("#kpi-cards").innerHTML = KPI_DEFS.map((d) => card(d)).join("");
  $("#kpi-status").innerHTML = KPI_STATUS.map((d) => card(d)).join("");
  chartData = await apiJSON("/api/charts");
  if ($("#view-dashboard").classList.contains("hidden")) {
    chartsNeedRender = true;
    return;
  }
  chartsNeedRender = false;
  renderCharts();
}
let _plotlyWaitTries = 0;
function renderCharts() {
  const c = chartData; if (!c) return;
  // Plotly is loaded with `defer` (so it never blocks the login page). If the
  // dashboard renders before that 4.5MB script finishes, wait and retry instead
  // of skipping - otherwise charts stay blank until a manual refresh.
  if (typeof Plotly === "undefined") {
    if (_plotlyWaitTries++ < 150) setTimeout(renderCharts, 50);
    else console.warn("Plotly did not load; charts skipped.");
    return;
  }
  _plotlyWaitTries = 0;
  const showEmpty = $("#toggle-empty").checked;
  const L = { margin: { t: 10, r: 10, b: 40, l: 40 }, font: { size: 11 }, showlegend: false, ...NO_ZOOM_AXES };
  const colors = (n) => Array.from({ length: n }, (_, i) => PAL[i % PAL.length]);
  const pieLegend = { showlegend: true, legend: { orientation: "v", font: { size: 10 } } };
  let d = themedPairs(c.status_distribution, CHART_THEMES.status);
  Plotly.newPlot("chart-status", [{ type: "pie", labels: d.labels, values: d.values, hole: .5, marker: { colors: d.colors }, sort: false }], { ...L, ...pieLegend }, PLOT_CFG);
  d = themedPairs(c.issue_source_distribution, CHART_THEMES.issueSource);
  Plotly.newPlot("chart-issuesource", [{ type: "bar", x: d.labels, y: d.values, marker: { color: d.colors } }], { ...L, margin: { t: 10, r: 10, b: 70, l: 40 } }, PLOT_CFG);
  d = themedPairs(c.source_comparison, CHART_THEMES.link);
  Plotly.newPlot("chart-source", [{ type: "pie", labels: d.labels, values: d.values, marker: { colors: d.colors }, sort: false }], { ...L, ...pieLegend }, PLOT_CFG);
  d = themedPairs(c.priority_distribution, CHART_THEMES.priority);
  Plotly.newPlot("chart-priority", [{ type: "bar", x: d.labels, y: d.values, marker: { color: d.colors } }], { ...L, margin: { t: 10, r: 10, b: 48, l: 40 } }, PLOT_CFG);
  d = themedPairs(c.validation_distribution, CHART_THEMES.validation);
  Plotly.newPlot("chart-validation", [{ type: "pie", labels: d.labels, values: d.values, marker: { colors: d.colors }, sort: false }], { ...L, ...pieLegend }, PLOT_CFG);
  const devRows = cleanChartRows(c.developer_distribution);
  const owner = (s) => String(s || "").replace(/[-_ ]?contractor_cel$/i, "").replace(/_cel$/i, "").replace(/[-_]/g, " ").trim();
  const devItems = devRows.map(([lbl, val]) => ({ label: owner(lbl), value: val })).sort((a, b) => b.value - a.value);
  const devColors = devItems.map((_, i) => PAL[i % PAL.length]);
  Plotly.newPlot("chart-dev", [
    { type: "bar", orientation: "h", y: devItems.map((x) => x.label).reverse(), x: devItems.map((x) => x.value).reverse(), marker: { color: devColors.slice().reverse() }, hovertemplate: "%{y}: %{x}<extra></extra>" },
  ], { ...L, margin: { t: 10, r: 10, b: 30, l: 10 }, xaxis: { gridcolor: "#eef2f7", zeroline: false, fixedrange: true }, yaxis: { automargin: true, fixedrange: true } }, PLOT_CFG);
  d = moduleChartPairs(c.module_distribution);
  const modBottom = Math.min(200, 56 + Math.max(0, d.labels.length - 4) * 6);
  Plotly.newPlot("chart-module", [{ type: "bar", x: d.labels, y: d.values, marker: { color: d.colors } }], {
    ...L,
    margin: { t: 10, r: 10, b: modBottom, l: 40 },
    xaxis: { ...NO_ZOOM_AXES.xaxis, automargin: true, tickangle: d.labels.length > 6 ? -40 : -25 },
  }, PLOT_CFG);
  resizeDashboardCharts();
}
document.addEventListener("change", (e) => { if (e.target && e.target.id === "toggle-empty") renderCharts(); });
window.addEventListener("resize", () => {
  if (!$("#view-dashboard").classList.contains("hidden")) resizeDashboardCharts();
});

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
      <td>${d.github_issue_id ? `<a href="#" class="gh-link">#${esc(d.github_issue_id)}</a>` : esc(d.github_issue_id) || "—"}</td>
      <td title="${esc(d.defect_title)}">${esc(d.defect_title)}</td>
      <td>${esc(d.github_status)}</td>
      <td>${statusPill(d.consolidated_status)}</td>
      <td>${esc(d.assigned_developer)}</td><td>${esc(d.priority)}</td>
      <td>${esc(d.issue_source)}</td>
      <td><span class="tag">${d.source_availability === "Both" ? "Linked" : "Not linked"}</span></td>
      <td>${esc(d.customer_defect_id)}</td>
      <td>${esc(d.customer_status)}</td>
      <td class="row-actions">
        <button class="btn" data-act="view">View</button>
        ${canU ? `<button class="btn" data-act="edit">Edit</button>` : ""}
        ${canD ? `<button class="btn btn-danger" data-act="del">Del</button>` : ""}
      </td></tr>`).join("") || `<tr><td colspan="11" style="text-align:center;padding:30px" class="muted">No defects match your filters.</td></tr>`;
  $("#pg-info").textContent = `Page ${data.page} of ${data.pages} · ${data.total} defects`;
  $("#pg-prev").disabled = data.page <= 1; $("#pg-next").disabled = data.page >= data.pages;
}
$("#defect-tbody").addEventListener("click", (e) => {
  const tr = e.target.closest("tr");
  if (!tr) return;
  if (e.target.closest("a")) e.preventDefault();
  const btn = e.target.closest("button");
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
  const rows = [["Action ID", d.customer_defect_id], ["GitHub Issue ID", d.github_issue_id], ["Consolidated Status", d.consolidated_status],
    ["Smart Sheet Status", d.customer_status], ["GitHub Status", d.github_status], ["Assigned Owner", d.assigned_developer], ["Priority", d.priority],
    ["Issue Source", d.issue_source], ["Module", d.module], ["NTT Category", d.ntt_category], ["Link", d.source_availability === "Both" ? "Linked to GitHub" : "Not linked"],
    ["Data Validation", d.data_validation_status], ["Created", d.created_date], ["Last Updated", d.last_updated],
    ["Development Progress", d.development_progress], ["Latest Comment", d.latest_comment], ["Description", d.description]];
  $("#modal-body").innerHTML = rows.map(([k, v]) => `<div class="detail-row"><div class="k">${k}</div><div class="detail-value">${esc(v) || "—"}</div></div>`).join("") +
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
let chatHistory = [], chatInit = false, chartSeq = 0, chatPending = false;
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
function distChartPairs(rows) {
  return rows.slice(0, 10).map((row) => {
    if (!row || typeof row !== "object") return null;
    let label = row.label ?? row.developer ?? row.issue_source;
    if (label == null) {
      const k = Object.keys(row).find((x) => x !== "count");
      label = k ? row[k] : "";
    }
    return { label: String(label ?? ""), value: Number(row.count) || 0 };
  }).filter(Boolean);
}
function miniChartLayout(c, horiz) {
  const maxV = Math.max(1, ...c.values.map((v) => Number(v) || 0));
  const yTop = Math.ceil(maxV * 1.12);
  const base = { font: { size: 10 }, height: 200, dragmode: false, bargap: 0.28, showlegend: false };
  if (horiz) {
    return {
      ...base,
      margin: { t: 6, r: 10, b: 30, l: 120 },
      xaxis: { fixedrange: true, rangemode: "tozero", range: [0, yTop], showgrid: true, gridcolor: "#eef2f7" },
      // type:category keeps labels (incl. ISO dates) as discrete bars, never a time axis
      yaxis: { fixedrange: true, automargin: true, type: "category" },
    };
  }
  const many = c.labels.length > 5;
  return {
    ...base,
    margin: { t: 6, r: 8, b: many ? 72 : 48, l: 44 },
    // type:category prevents Plotly from treating a lone ISO date as a time axis
    xaxis: { fixedrange: true, automargin: true, tickangle: many ? -35 : -20, type: "category" },
    yaxis: { fixedrange: true, rangemode: "tozero", range: [0, yTop], showgrid: true, gridcolor: "#eef2f7", zeroline: false },
  };
}
function renderMiniChart(c) {
  const horiz = c.orient === "h";
  const values = c.values.map((v) => Number(v) || 0);
  const labels = c.labels.map((l) => String(l));
  const cols = labels.map((_, i) => PAL[i % PAL.length]);
  const trace = horiz
    ? { type: "bar", orientation: "h", y: labels.slice().reverse(), x: values.slice().reverse(), marker: { color: cols.slice().reverse() } }
    : { type: "bar", x: labels, y: values, marker: { color: cols } };
  const layout = miniChartLayout({ labels, values }, horiz);
  requestAnimationFrame(() => {
    if (!document.getElementById(c.id)) return;
    Plotly.newPlot(c.id, [trace], layout, PLOT_CFG).then(() => Plotly.Plots.resize(c.id));
  });
}
function buildVisual(data) {
  if (!data) return { html: "", charts: [] };
  const rows = data.rows || [], extra = data.extra || {}, tool = data.tool || (data.meta && data.meta.tool);
  const charts = []; let html = "";
  const chart = (spec) => { const id = "mc" + (++chartSeq); charts.push({ id, ...spec }); return `<div id="${id}" class="mini-chart"></div>`; };
  if (tool === "summary" && extra.total_defects != null) {
    html += statRow([["Total", extra.total_defects], ["Open", extra.open_defects], ["In Prog", extra.in_progress], ["Closed", extra.closed_defects]]);
    html += chart({ labels: ["Open", "In Progress", "Closed"], values: [extra.open_defects, extra.in_progress, extra.closed_defects], orient: "v" });
  } else if (rows[0] && typeof rows[0] === "object" && "count" in rows[0]) {
    const pairs = distChartPairs(rows);
    const useHoriz = tool === "developer_distribution" || pairs.length > 6;
    html += chart({
      labels: pairs.map((p) => p.label),
      values: pairs.map((p) => p.value),
      orient: useHoriz ? "h" : "v",
    });
  } else if (tool === "defects_by_date") {
    // daily rows are handled by the distribution branch above; this is the total case
    html += statRow([[(data.args && data.args.status) || "Defects", data.count]]);
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
  vis.charts.forEach((c) => renderMiniChart(c));
  el.querySelectorAll("table.mini tbody tr").forEach((tr) => tr.addEventListener("click", () => { if (tr.dataset.rid) openDetail(tr.dataset.rid); }));
}
function showChatLoader() {
  const el = document.createElement("div");
  el.className = "msg bot loading";
  el.setAttribute("aria-live", "polite");
  el.innerHTML = '<div class="chat-loader" role="status"><span class="chat-spinner" aria-hidden="true"></span><span class="chat-loader-text">Thinking…</span></div>';
  $("#chat-log").appendChild(el);
  $("#chat-log").scrollTop = 1e9;
  return el;
}
async function sendChat() {
  const text = $("#chat-text").value.trim();
  if (!text || chatPending) return;
  chatPending = true;
  const input = $("#chat-text");
  const sendBtn = $("#chat-form button");
  input.disabled = true;
  sendBtn.disabled = true;
  input.value = "";
  addUserMessage(text);
  chatHistory.push({ role: "user", content: text });
  const thinking = showChatLoader();
  try {
    const resp = await apiJSON("/api/chat", { method: "POST", body: JSON.stringify({ message: text, history: chatHistory.slice(-8) }) });
    thinking.remove();
    addBotMessage(resp.reply, resp.data);
    chatHistory.push({ role: "assistant", content: resp.reply });
  } catch (e) {
    thinking.remove();
    addBotMessage("Sorry, I hit an error: " + e.message, null);
  } finally {
    chatPending = false;
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
  }
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
