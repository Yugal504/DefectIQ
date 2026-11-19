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
  if (view === "insights") loadInsights();
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
// Dark-theme plot defaults: transparent canvas so the card shows through,
// light tick/label text, and subtle gridlines that read on a dark panel.
const PLOT_BG = "rgba(0,0,0,0)";
const PLOT_FONT_COLOR = "#c4d3ea";
const PLOT_GRID = "rgba(148,170,200,.16)";
const NO_ZOOM_AXES = { dragmode: false,
  xaxis: { fixedrange: true, gridcolor: PLOT_GRID, zerolinecolor: PLOT_GRID },
  yaxis: { fixedrange: true, gridcolor: PLOT_GRID, zerolinecolor: PLOT_GRID } };
const PIE_TEXT = { color: "#ffffff", size: 11 };
function pieTrace(d, { hole } = {}) {
  const t = {
    type: "pie", labels: d.labels, values: d.values, marker: { colors: d.colors }, sort: false,
    textfont: PIE_TEXT, outsidetextfont: PIE_TEXT, insidetextfont: PIE_TEXT,
    hoverlabel: { font: { color: "#ffffff", size: 12 } },
  };
  if (hole != null) t.hole = hole;
  return t;
}
// Muted, lower-saturation palette that sits calmly on the dark navy canvas.
const PAL = ["#4a90c4", "#4fb0a2", "#cfa255", "#c47a73", "#8b82b8", "#5b9ec0", "#6ea890", "#bb8a66", "#7faa8c", "#a089b3"];
const EMPTY_LABELS = ["(none)", "unspecified", "unknown", "(unassigned)", "n/a", ""];
const isEmptyLabel = (lbl) => EMPTY_LABELS.includes(String(lbl ?? "").trim().toLowerCase());
const normChartKey = (s) => String(s ?? "").trim().toLowerCase().replace(/\s+/g, " ");
const CHART_THEMES = {
  status: {
    order: ["Open", "In Progress", "Closed", "Unknown"],
    colors: { open: "#cfa255", "in progress": "#4a90c4", closed: "#4fb0a2", unknown: "#7a8aa0" },
  },
  priority: {
    order: ["Critical/Urgent", "Critical", "High", "Medium", "Low", "Unknown", "(none)"],
    colors: {
      "critical/urgent": "#b5544c",
      critical: "#c47a73",
      high: "#c08a5e",
      medium: "#cfa255",
      low: "#4fb0a2",
      unknown: "#7a8aa0",
      "(none)": "#8b97aa",
      none: "#8b97aa",
    },
  },
  validation: {
    order: ["Matched", "Missing", "Duplicate", "Requires Review", "Unknown"],
    colors: { matched: "#4fb0a2", missing: "#c47a73", duplicate: "#8b82b8", "requires review": "#cfa255", unknown: "#7a8aa0" },
  },
  link: {
    order: ["Linked to GitHub", "Not Linked"],
    colors: { "linked to github": "#4fb0a2", "not linked": "#4a90c4" },
  },
  issueSource: {
    order: ["PROD", "UAT", "SIT", "DEV", "QA", "Exception Triage", "Shared Mailbox", "(none)"],
    colors: {
      prod: "#c47a73",
      uat: "#c08a5e",
      sit: "#4a90c4",
      dev: "#4fb0a2",
      qa: "#8b82b8",
      "exception triage": "#5b9ec0",
      "shared mailbox": "#6ea890",
      "(none)": "#8b97aa",
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
  const L = {
    paper_bgcolor: PLOT_BG, plot_bgcolor: PLOT_BG, margin: { t: 10, r: 10, b: 40, l: 40 },
    font: { size: 11, color: PLOT_FONT_COLOR }, showlegend: false,
    hoverlabel: { font: { color: "#ffffff", size: 12 } },
    ...NO_ZOOM_AXES,
  };
  const colors = (n) => Array.from({ length: n }, (_, i) => PAL[i % PAL.length]);
  const pieLegend = { showlegend: true, legend: { orientation: "v", font: { size: 10, color: PLOT_FONT_COLOR } } };
  let d = themedPairs(c.status_distribution, CHART_THEMES.status);
  Plotly.newPlot("chart-status", [pieTrace(d, { hole: 0.5 })], { ...L, ...pieLegend }, PLOT_CFG);
  d = themedPairs(c.issue_source_distribution, CHART_THEMES.issueSource);
  Plotly.newPlot("chart-issuesource", [{ type: "bar", x: d.labels, y: d.values, marker: { color: d.colors } }], { ...L, margin: { t: 10, r: 10, b: 70, l: 40 } }, PLOT_CFG);
  d = themedPairs(c.source_comparison, CHART_THEMES.link);
  Plotly.newPlot("chart-source", [pieTrace(d)], { ...L, ...pieLegend }, PLOT_CFG);
  d = themedPairs(c.priority_distribution, CHART_THEMES.priority);
  Plotly.newPlot("chart-priority", [{ type: "bar", x: d.labels, y: d.values, marker: { color: d.colors } }], { ...L, margin: { t: 10, r: 10, b: 48, l: 40 } }, PLOT_CFG);
  d = themedPairs(c.validation_distribution, CHART_THEMES.validation);
  Plotly.newPlot("chart-validation", [pieTrace(d)], { ...L, ...pieLegend }, PLOT_CFG);
  const devRows = cleanChartRows(c.developer_distribution);
  const owner = (s) => String(s || "").replace(/[-_ ]?contractor_cel$/i, "").replace(/_cel$/i, "").replace(/[-_]/g, " ").trim();
  const devItems = devRows.map(([lbl, val]) => ({ label: owner(lbl), value: val })).sort((a, b) => b.value - a.value);
  const devColors = devItems.map((_, i) => PAL[i % PAL.length]);
  Plotly.newPlot("chart-dev", [
    { type: "bar", orientation: "h", y: devItems.map((x) => x.label).reverse(), x: devItems.map((x) => x.value).reverse(), marker: { color: devColors.slice().reverse() }, hovertemplate: "%{y}: %{x}<extra></extra>" },
  ], { ...L, margin: { t: 10, r: 10, b: 30, l: 10 }, xaxis: { gridcolor: PLOT_GRID, zeroline: false, fixedrange: true }, yaxis: { automargin: true, fixedrange: true } }, PLOT_CFG);
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
  if (!$("#view-insights").classList.contains("hidden") && typeof Plotly !== "undefined"
      && document.getElementById("ins-weekly") && document.getElementById("ins-weekly").data) {
    Plotly.Plots.resize("ins-weekly");
  }
});

/* ----------------------------- Insights ----------------------------- */
const InsState = { filters: { issue_source: "", module: "", priority: "", status: "" }, last: null };
function insShowEmpty() { const el = $("#ins-toggle-empty"); return !!(el && el.checked); }
const INS_FILTER_DEFS = [["issue_source", "Issue Source"], ["module", "Module"], ["priority", "Priority"], ["status", "Status"]];
const INS_KPI_DEFS = [
  ["total", "Total", "k-ss"], ["open", "Open", "k-open"], ["closed", "Closed", "k-closed"],
  ["urgent", "Critical / Urgent", "k-missing"], ["unassigned", "Unassigned", "k-unassigned"],
  ["created_this_week", "Created this week", "k-linked"], ["closed_this_week", "Closed this week", "k-matched"],
  ["deployed_uat", "Deployed to UAT", "k-progress"],
];
const HEAT_BASE = { "open": "224,168,0", "closed": "23,166,115", "in progress": "10,102,194" };
function heatStyle(val, max, kind) {
  if (!val) return "";
  const base = HEAT_BASE[String(kind).toLowerCase()] || "10,102,194";
  const t = max > 0 ? val / max : 0;
  return `background: rgba(${base}, ${(0.12 + 0.6 * t).toFixed(2)});`;
}
async function loadInsights() {
  const p = new URLSearchParams();
  Object.entries(InsState.filters).forEach(([k, v]) => { if (v) p.set(k, v); });
  try {
    const r = await apiJSON("/api/insights" + (p.toString() ? "?" + p.toString() : ""));
    renderInsights(r);
  } catch (e) { toast(e.message); }
}
function renderInsights(r) {
  InsState.last = r;
  // filter bar — Reset sits in the same row as the dropdowns
  $("#ins-filters").innerHTML = INS_FILTER_DEFS.map(([key, label]) => {
    const opts = r.options[key] || [];
    const sel = InsState.filters[key];
    return `<div class="ins-filter"><label>${label}</label><select data-fk="${key}">
      <option value="">All</option>
      ${opts.map((o) => `<option ${o === sel ? "selected" : ""}>${esc(o)}</option>`).join("")}
    </select></div>`;
  }).join("") +
    `<div class="ins-filter ins-filter-reset"><label>&nbsp;</label>
       <button id="ins-reset" class="btn btn-ghost" title="Clear all filters">↺ Reset</button></div>`;
  $$("#ins-filters select").forEach((s) => s.addEventListener("change", () => { InsState.filters[s.dataset.fk] = s.value; loadInsights(); }));
  $("#ins-reset").addEventListener("click", resetInsFilters);
  // KPI tiles
  $("#ins-kpis").innerHTML = INS_KPI_DEFS.map(([key, label, cls]) =>
    `<div class="ins-kpi ${cls}"><div class="num">${r.kpis[key] ?? 0}</div><div class="lbl">${label}</div></div>`).join("");
  renderInsSummary(r.summary);
  renderInsMatrix(r.matrix);
  renderInsPriority(r.priority);
  renderInsWeekly(r.weekly);
  renderInsCountTable("#ins-promotion", r.promotion, "Workflow Phase", false, "promotion");
  renderInsCountTable("#ins-issuesource", r.issue_source, "Issue Source", false, "issue_source");
  renderInsCountTable("#ins-owners", r.owners, "Owner", true, "owner");
  renderInsUat(r.uat);
}
/* Summary as a 7-business-day progress grid (metric rows × dated day columns).
   Cells for activity/cumulative metrics stay interactive — click to see defects. */
function formatSummaryDayTh(label) {
  const s = String(label || "");
  const m = s.match(/^(\d+)(st|nd|rd|th)\s+(\w+)$/i);
  if (!m) return esc(s);
  const [, day, suf, mon] = m;
  return `${esc(day)}<sup class="day-ord">${esc(suf.toLowerCase())}</sup> <span class="day-mon">${esc(mon)}</span>`;
}
function insSummaryDrill(type, dayKey) {
  const minusDays = (iso, n) => {
    const d = new Date(iso + "T00:00:00");
    d.setDate(d.getDate() - n);
    return d.toISOString().slice(0, 10);
  };
  switch (type) {
    case "total": return { created_before: dayKey };
    case "open": return { open_as_of: dayKey };
    case "closed_cum": return { status: ["Closed"], closed_before: dayKey };
    case "ageing": return { open_as_of: dayKey, created_before: minusDays(dayKey, 30) };
    case "urgent": return { open_as_of: dayKey, priority: ["Critical/Urgent"] };
    case "created_on": return { created_since: dayKey, created_before: dayKey };
    case "closed_on": return { status: ["Closed"], closed_since: dayKey, closed_before: dayKey };
    default: return null;
  }
}
function renderInsSummary(summary) {
  summary = summary || { days: [], rows: [] };
  const days = summary.days || [];
  const head = `<thead><tr><th>Metric</th>${days.map((d) =>
    `<th class="num day-hdr" title="${esc(d.key)}">${formatSummaryDayTh(d.label)}</th>`).join("")}</tr></thead>`;
  const body = (summary.rows || []).map((r) => {
    const drillable = !!r.drill;
    const cells = (r.values || []).map((v, i) => {
      const cls = `num sumval${i === 0 ? " today" : ""}${drillable ? " cell-click" : ""}`;
      const data = drillable ? ` data-drill="${esc(r.drill)}" data-day="${esc((days[i] || {}).key || "")}" data-label="${esc((days[i] || {}).label || "")}"` : "";
      return `<td class="${cls}"${data}>${v}</td>`;
    }).join("");
    return `<tr class="sum-${r.tone}"><td class="rowlbl"><span class="tone-dot"></span>${esc(r.metric)}</td>${cells}</tr>`;
  }).join("");
  $("#ins-summary").innerHTML = head + `<tbody>${body}</tbody>`;
  $$("#ins-summary td.cell-click").forEach((td) => td.addEventListener("click", () => {
    const o = insSummaryDrill(td.dataset.drill, td.dataset.day);
    if (o) openInsDrill(`${td.closest("tr").querySelector(".rowlbl").textContent.trim()} · ${td.dataset.label}`, o);
  }));
}
function renderInsMatrix(m) {
  const cols = m.columns;
  // honor the "None / Unspecified" toggle; recompute totals from visible rows
  const rows = insShowEmpty() ? m.rows : m.rows.filter((row) => !isEmptyLabel(row.label));
  const colTotals = cols.map((_, i) => rows.reduce((s, row) => s + (row.cells[i] || 0), 0));
  const grand = colTotals.reduce((a, b) => a + b, 0);
  const maxCell = Math.max(1, ...rows.flatMap((row) => row.cells.map((v) => v || 0)));
  const head = `<thead><tr><th>Module</th>${cols.map((c) => `<th class="num">${c}</th>`).join("")}<th class="num">Total</th></tr></thead>`;
  const body = rows.map((row) => `<tr>
    <td class="rowlbl" title="${esc(row.label)}">${esc(row.label)}</td>
    ${row.cells.map((v, i) => `<td class="num cell-click" data-status="${esc(cols[i])}" data-module="${esc(row.label)}" style="${heatStyle(v, maxCell, cols[i])}">${v || ""}</td>`).join("")}
    <td class="num total">${row.total}</td></tr>`).join("");
  const foot = `<tr class="totrow"><td>Total</td>${colTotals.map((v) => `<td class="num">${v}</td>`).join("")}<td class="num">${grand}</td></tr>`;
  $("#ins-matrix").innerHTML = head + `<tbody>${body}${foot}</tbody>`;
  $$("#ins-matrix .cell-click").forEach((td) => td.addEventListener("click", () => {
    const mod = td.dataset.module, st = td.dataset.status;
    openInsDrill(`${mod} · ${st}`, { module: [mod], status: [st] });
  }));
}
/* Drill-down: show the actual defects behind any clicked Insights number, in a
   modal, respecting the page's current filters. Click a row for full detail. */
async function openInsDrill(title, overrides) {
  const p = new URLSearchParams();
  const setList = (k, v) => { if (v && v.length) p.set(k, v.join(",")); };
  // start from the page filters, then apply the clicked cell's overrides
  const merged = { ...InsState.filters };
  Object.entries(overrides).forEach(([k, v]) => { merged[k] = v; });
  Object.entries(merged).forEach(([k, v]) => {
    const arr = Array.isArray(v) ? v : (v ? [v] : []);
    setList(k, arr);
  });
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = `<div class="muted" style="padding:14px">Loading…</div>`;
  $("#modal").classList.add("modal-lg");
  $("#modal").classList.remove("hidden");
  try {
    const data = await apiJSON("/api/insights/drill?" + p.toString());
    if (!data.items.length) {
      $("#modal-body").innerHTML = `<div class="muted" style="padding:14px">No matching defects.</div>`;
      return;
    }
    const rows = data.items.map((d) => `<tr data-rid="${esc(d.record_id)}">
      <td>${d.github_issue_id ? "#" + esc(d.github_issue_id) : "—"}</td>
      <td title="${esc(d.defect_title)}">${esc((d.defect_title || "").slice(0, 70))}</td>
      <td>${statusPill(d.consolidated_status)}</td>
      <td>${esc(d.priority)}</td>
      <td>${esc(d.assigned_developer) || "—"}</td>
      <td>${esc(d.ntt_category) || "—"}</td>
      <td>${esc(d.module) || "—"}</td></tr>`).join("");
    $("#modal-body").innerHTML = `<div class="drill-count muted small">${data.count} defect(s)</div>
      <div class="table-wrap"><table class="perf-table list">
      <thead><tr><th>GitHub</th><th>Title</th><th>Status</th><th>Priority</th><th>Assigned To</th><th>Category</th><th>Module</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
    $$("#modal-body table.list tbody tr").forEach((tr) => tr.addEventListener("click", () => { if (tr.dataset.rid) openDetail(tr.dataset.rid); }));
  } catch (e) {
    $("#modal-body").innerHTML = `<div class="error" style="padding:14px">${esc(e.message)}</div>`;
  }
}
function renderInsPriority(allRows) {
  const rows = insShowEmpty() ? allRows : allRows.filter((r) => !isEmptyLabel(r.label));
  const max = Math.max(1, ...rows.map((r) => r.total));
  const head = `<thead><tr><th>Priority</th><th class="num">Open</th><th class="num">Closed</th><th class="num">Total</th></tr></thead>`;
  const body = rows.map((r) => `<tr>
    <td class="rowlbl">${esc(r.label)}</td>
    <td class="num cell-click" data-p="${esc(r.label)}" data-s="Open" style="${heatStyle(r.open, max, 'open')}">${r.open || ""}</td>
    <td class="num cell-click" data-p="${esc(r.label)}" data-s="Closed" style="${heatStyle(r.closed, max, 'closed')}">${r.closed || ""}</td>
    <td class="num total cell-click" data-p="${esc(r.label)}" data-s="">${r.total}</td></tr>`).join("");
  $("#ins-priority").innerHTML = head + `<tbody>${body}</tbody>`;
  $$("#ins-priority .cell-click").forEach((td) => td.addEventListener("click", () => {
    const o = { priority: [td.dataset.p] };
    if (td.dataset.s) o.status = [td.dataset.s];
    openInsDrill(`${td.dataset.p}${td.dataset.s ? " · " + td.dataset.s : ""}`, o);
  }));
}
function renderInsCountTable(sel, allPairs, header, cleanOwner, drillKey) {
  const pairs = insShowEmpty() ? allPairs : allPairs.filter(([lbl]) => !isEmptyLabel(lbl));
  const max = Math.max(1, ...pairs.map((p) => p[1]));
  const name = (s) => cleanOwner ? String(s || "").replace(/[-_ ]?contractor_cel$/i, "").replace(/_cel$/i, "").replace(/[-_]/g, " ").trim() : s;
  const body = pairs.map(([lbl, val]) => `<tr class="cell-click" data-v="${esc(lbl)}">
    <td class="rowlbl" title="${esc(lbl)}">${esc(name(lbl)) || "—"}</td>
    <td class="num barcell"><span class="ibar" style="width:${Math.round(100 * val / max)}%"></span><span class="bval">${val}</span></td></tr>`).join("")
    || `<tr><td colspan="2" class="muted" style="text-align:center;padding:12px">No data.</td></tr>`;
  $(sel).innerHTML = `<thead><tr><th>${header}</th><th class="num">Count</th></tr></thead><tbody>${body}</tbody>`;
  if (drillKey) {
    $$(sel + " tr.cell-click").forEach((tr) => tr.addEventListener("click", () => {
      const o = {}; o[drillKey] = [tr.dataset.v];
      if (drillKey === "owner") o.status = ["Open"];
      openInsDrill(name(tr.dataset.v) || tr.dataset.v, o);
    }));
  }
}
function renderInsWeekly(w) {
  if (typeof Plotly === "undefined") { setTimeout(() => renderInsWeekly(w), 80); return; }
  const dayLbl = w.days.map((d) => d.slice(5));
  const L = { paper_bgcolor: PLOT_BG, plot_bgcolor: PLOT_BG, barmode: "group", margin: { t: 8, r: 8, b: 28, l: 28 }, height: 220, bargap: 0.3, font: { size: 11, color: PLOT_FONT_COLOR },
    legend: { orientation: "h", y: 1.15, font: { size: 10 } }, ...NO_ZOOM_AXES,
    xaxis: { type: "category", fixedrange: true }, yaxis: { fixedrange: true, rangemode: "tozero", gridcolor: PLOT_GRID } };
  Plotly.newPlot("ins-weekly", [
    { type: "bar", name: "Created", x: dayLbl, y: w.created, marker: { color: "#4a90c4" } },
    { type: "bar", name: "Closed", x: dayLbl, y: w.closed, marker: { color: "#4fb0a2" } },
  ], L, PLOT_CFG).then(() => Plotly.Plots.resize("ins-weekly"));
}
function renderInsUat(rows) {
  $("#ins-uat-count").textContent = `(${rows.length})`;
  const head = `<thead><tr><th>GitHub</th><th>Title</th><th>Module</th><th>Owner</th><th>Priority</th><th>Phase</th></tr></thead>`;
  const body = rows.map((r) => `<tr data-rid="${esc(r.record_id)}">
    <td>${r.github_issue_id ? "#" + esc(r.github_issue_id) : "—"}</td>
    <td title="${esc(r.defect_title)}">${esc((r.defect_title || "").slice(0, 60))}</td>
    <td>${esc(r.module)}</td><td>${esc(r.assigned_developer)}</td>
    <td>${esc(r.priority)}</td><td>${esc(r.promotion_status)}</td></tr>`).join("")
    || `<tr><td colspan="6" class="muted" style="text-align:center;padding:16px">No issues deployed for UAT in this view.</td></tr>`;
  $("#ins-uat").innerHTML = head + `<tbody>${body}</tbody>`;
  $$("#ins-uat tbody tr").forEach((tr) => tr.addEventListener("click", () => { if (tr.dataset.rid) openDetail(tr.dataset.rid); }));
}
function resetInsFilters() { InsState.filters = { issue_source: "", module: "", priority: "", status: "" }; loadInsights(); }
$("#ins-toggle-empty").addEventListener("change", () => { if (InsState.last) renderInsights(InsState.last); });

/* ----------------------------- Defects ----------------------------- */
function statusPill(s) { const cls = { "Open": "p-open", "In Progress": "p-inprogress", "Closed": "p-closed" }[s] || "p-unknown"; return `<span class="pill ${cls}">${s || "—"}</span>`; }
function filterParams() {
  const p = new URLSearchParams(); const add = (k, v) => { if (v) p.set(k, v); };
  add("search", $("#f-search").value); add("status", $("#f-status").value);
  add("issue_source", $("#f-issuesource").value); add("module", $("#f-module").value);
  add("priority", $("#f-priority").value);
  p.set("sort", State.sort); p.set("order", State.order); return p;
}
/* Defects page uses the SAME filter set as Insights (Issue Source, Module,
   Priority, Status), populated from the shared /api/filter-options endpoint. */
let _defFilterOpts = null;
async function ensureDefectFilters() {
  if (_defFilterOpts) return;
  _defFilterOpts = await apiJSON("/api/filter-options");
  const fill = (sel, items, allLbl) => {
    const el = $(sel); if (!el) return;
    const cur = el.value;
    el.innerHTML = `<option value="">${allLbl}</option>` + (items || []).map((o) => `<option>${esc(o)}</option>`).join("");
    el.value = cur;
  };
  fill("#f-issuesource", _defFilterOpts.issue_source, "All Issue Sources");
  fill("#f-module", _defFilterOpts.module, "All Modules");
  fill("#f-priority", _defFilterOpts.priority, "All Priorities");
  fill("#f-status", _defFilterOpts.status, "All Statuses");
}
function updateDefectSortHeaders() {
  $$("#defect-table th[data-sort]").forEach((th) => {
    th.classList.remove("sort-asc", "sort-desc", "sort-idle");
    if (th.dataset.sort === State.sort) th.classList.add(State.order === "asc" ? "sort-asc" : "sort-desc");
    else th.classList.add("sort-idle");
    const on = th.dataset.sort === State.sort;
    th.setAttribute("aria-sort", on ? (State.order === "asc" ? "ascending" : "descending") : "none");
  });
}
async function loadDefects() {
  await ensureDefectFilters();
  const p = filterParams(); p.set("page", State.page); p.set("page_size", State.pageSize);
  const data = await apiJSON("/api/defects?" + p.toString());
  State.totalPages = data.pages || 1;
  const total = data.total ?? 0;
  $("#defect-total").innerHTML = `Total defects: <strong>${Number(total).toLocaleString()}</strong>`;
  updateDefectSortHeaders();
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
// dropdowns reload immediately on change, like the Insights filters
["#f-issuesource", "#f-module", "#f-priority", "#f-status"].forEach((sel) =>
  $(sel).addEventListener("change", () => { State.page = 1; loadDefects(); }));
$("#f-reset").addEventListener("click", () => {
  $("#f-search").value = "";
  ["#f-issuesource", "#f-module", "#f-priority", "#f-status"].forEach((sel) => { $(sel).value = ""; });
  State.page = 1; loadDefects();
});
$("#pg-prev").addEventListener("click", () => { if (State.page > 1) { State.page--; loadDefects(); } });
$("#pg-next").addEventListener("click", () => { if (State.page < State.totalPages) { State.page++; loadDefects(); } });
$$("#defect-table th[data-sort]").forEach((th) => th.addEventListener("click", () => {
  const col = th.dataset.sort;
  if (State.sort === col) State.order = State.order === "asc" ? "desc" : "asc"; else { State.sort = col; State.order = "asc"; }
  State.page = 1;
  updateDefectSortHeaders();
  loadDefects();
}));
updateDefectSortHeaders();

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
  $("#modal").classList.remove("modal-lg");
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
  $("#modal").classList.remove("modal-lg");
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
const DEFAULT_SUGGESTIONS = ["Defect summary", "How many critical defects are open?", "Which module has the most open defects?", "Oldest open defects", "Who has the most open urgent defects?", "By issue source", "Any duplicates?"];
const SUGG_KEY = "defectiq.suggestions";
const LIST_TOOLS = ["list_defects", "unassigned_defects", "reconciliation_gaps", "search_defects", "defect_detail"];
let chatHistory = [], chatInit = false, chartSeq = 0, chatPending = false;

/* Frequently-asked questions are editable and persisted per browser. */
function loadSuggestions() {
  try { const s = JSON.parse(localStorage.getItem(SUGG_KEY)); if (Array.isArray(s) && s.length) return s; } catch (e) { /* ignore */ }
  return DEFAULT_SUGGESTIONS.slice();
}
function saveSuggestions(arr) { localStorage.setItem(SUGG_KEY, JSON.stringify(arr)); }
function renderSuggestions() {
  const items = loadSuggestions();
  $("#chat-suggestions").innerHTML =
    items.map((s) => `<button class="sugg">${esc(s)}</button>`).join("") +
    `<button class="sugg-edit" title="Edit frequently asked questions">✎ Edit</button>`;
  $$("#chat-suggestions button.sugg").forEach((b) => b.addEventListener("click", () => { $("#chat-text").value = b.textContent; sendChat(); }));
  $("#chat-suggestions .sugg-edit").addEventListener("click", openSuggestionEditor);
}
function openSuggestionEditor() {
  const items = loadSuggestions();
  $("#modal-title").textContent = "Edit frequently asked questions";
  $("#modal-body").innerHTML = `
    <p class="muted small" style="margin-top:0">One question per line. These show as quick-ask chips in the assistant.</p>
    <textarea id="sugg-edit-text" style="width:100%;min-height:230px;padding:10px;border:1px solid var(--border);border-radius:8px;background:#0b1626;color:var(--text);font-family:inherit;font-size:13px;line-height:1.7;resize:vertical">${esc(items.join("\n"))}</textarea>
    <div class="modal-actions">
      <button id="sugg-reset" class="btn btn-ghost">Reset to default</button>
      <button id="sugg-save" class="btn btn-primary">Save</button>
    </div>`;
  $("#modal").classList.remove("hidden");
  $("#sugg-reset").addEventListener("click", () => { $("#sugg-edit-text").value = DEFAULT_SUGGESTIONS.join("\n"); });
  $("#sugg-save").addEventListener("click", () => {
    const lines = $("#sugg-edit-text").value.split("\n").map((s) => s.trim()).filter(Boolean);
    saveSuggestions(lines.length ? lines : DEFAULT_SUGGESTIONS.slice());
    renderSuggestions();
    $("#modal").classList.add("hidden");
    toast("Frequently asked questions updated");
  });
}
function initChat() {
  if (chatInit) return; chatInit = true;
  renderSuggestions();
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
  const base = { paper_bgcolor: PLOT_BG, plot_bgcolor: PLOT_BG, font: { size: 10, color: PLOT_FONT_COLOR }, height: 200, dragmode: false, bargap: 0.28, showlegend: false };
  if (horiz) {
    return {
      ...base,
      margin: { t: 6, r: 10, b: 30, l: 120 },
      xaxis: { fixedrange: true, rangemode: "tozero", range: [0, yTop], showgrid: true, gridcolor: PLOT_GRID },
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
    yaxis: { fixedrange: true, rangemode: "tozero", range: [0, yTop], showgrid: true, gridcolor: PLOT_GRID, zeroline: false },
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
