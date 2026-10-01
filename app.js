"use strict";

// Categorical palette: hematoxylin/eosin first, then distinct, colorblind-aware hues.
const PALETTE = [
  "#3A3F9E", "#C2457E", "#2A9D8F", "#E9A23B", "#6C8EBF", "#8E5572", "#4E9F3D", "#D1603D",
  "#7A6FB0", "#3F7F93", "#B5838D", "#A0A83B", "#5E548E", "#E07A5F", "#2F6690", "#9C6644",
  "#43AA8B", "#C9A227", "#8D99AE", "#BC4B51",
];
const NONE = "";
const $ = (id) => document.getElementById(id);

const state = { dataset: null, schema: null, offset: 0, limit: 50, sort: null, desc: false, q: "" };

// ------------------------------------------------------------ helpers
async function api(path) {
  const res = await fetch(path);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
  return body;
}
const enc = encodeURIComponent;
const dsPath = (suffix, params = {}) => {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== NONE));
  return `/api/datasets/${state.dataset.split("/").map(enc).join("/")}/${suffix}${qs.toString() ? "?" + qs : ""}`;
};

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), 6000);
}

function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function naturalSort(values) {
  return [...values].sort((a, b) => {
    const na = Number(a), nb = Number(b);
    if (a !== null && b !== null && !isNaN(na) && !isNaN(nb)) return na - nb;
    if (a === null) return 1;
    if (b === null) return -1;
    return String(a).localeCompare(String(b), undefined, { numeric: true });
  });
}

function fillSelect(el, options, { blank } = {}) {
  el.innerHTML = "";
  if (blank) el.append(new Option(blank, NONE));
  for (const o of options) el.append(new Option(o, o));
}

function swatch(i) {
  if (i === 0) return css("--hema");
  if (i === 1) return css("--eosin");
  return PALETTE[i % PALETTE.length];
}
const narrow = () => matchMedia("(max-width: 640px)").matches;

function column(name) { return state.schema.columns.find((c) => c.name === name); }

function baseLayout() {
  const ink = css("--ink"), muted = css("--muted"), line = css("--line");
  return {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: css("--sans"), color: ink, size: 13 },
    margin: { l: 56, r: 16, t: 28, b: 48 },
    xaxis: { gridcolor: line, zerolinecolor: line, linecolor: line, tickfont: { color: muted } },
    yaxis: { gridcolor: line, zerolinecolor: line, linecolor: line, tickfont: { color: muted } },
    legend: narrow()
      ? { itemsizing: "constant", font: { size: 12 }, orientation: "h", x: 0, y: -0.22, yanchor: "top" }
      : { itemsizing: "constant", font: { size: 12 } },
    hoverlabel: { font: { family: css("--sans") } },
  };
}
const PLOT_CONFIG = {
  responsive: true,
  displaylogo: false,
  toImageButtonOptions: { format: "svg", filename: "t1d-clusters" },
  modeBarButtonsToRemove: ["lasso2d", "select2d", "zoomIn2d", "zoomOut2d", "autoScale2d"],
};

// --------------------------------------------------- URL (shareable views)
function readHash() { return Object.fromEntries(new URLSearchParams(location.hash.slice(1))); }
const EMBED_IDS = ["x", "y", "color", "compare", "hover"];
const FOREST_IDS = ["f-label", "f-est", "f-lower", "f-upper", "f-se", "f-p", "f-group", "f-panel"];
function writeHash() {
  const view = $("view").value;
  const p = new URLSearchParams({ dataset: state.dataset, view });
  const ids = view === "forest" ? FOREST_IDS : view === "embedding" ? EMBED_IDS : [];
  for (const id of ids) if ($(id).value) p.set(id, $(id).value);
  if (view === "forest") p.set("ratio", $("f-ratio").checked ? "1" : "0");
  history.replaceState(null, "", "#" + p.toString());
}

// ------------------------------------------------------------ loading
async function init() {
  let list;
  try {
    list = await api("/api/datasets");
  } catch (e) {
    $("dataset-meta").textContent = "Could not reach the server.";
    return toast(e.message);
  }
  if (!list.datasets.length) {
    document.querySelector(".workspace").hidden = true;
    $("empty").hidden = false;
    $("dataset-meta").textContent = "No datasets yet";
    if (list.data_dir) $("empty-dir").textContent = `The server is reading from ${list.data_dir}`;
    return;
  }
  fillSelect($("dataset"), list.datasets.map((d) => d.name));
  const wanted = readHash();
  const start = list.datasets.some((d) => d.name === wanted.dataset) ? wanted.dataset : list.datasets[0].name;
  $("dataset").value = start;
  await loadDataset(start, wanted);
}

async function loadDataset(name, preset = {}) {
  state.dataset = name;
  Object.assign(state, { offset: 0, sort: null, desc: false, q: "" });
  $("search").value = "";
  try {
    state.schema = await api(dsPath("schema"));
  } catch (e) { return toast(e.message); }

  const cols = state.schema.columns;
  const numeric = cols.filter((c) => c.numeric).map((c) => c.name);
  const categorical = cols.filter((c) => c.categorical).map((c) => c.name);
  const colorable = [...new Set([...categorical, ...numeric])];

  fillSelect($("x"), numeric);
  fillSelect($("y"), numeric);
  fillSelect($("color"), colorable, { blank: "None" });
  fillSelect($("compare"), categorical, { blank: "None" });
  fillSelect($("hover"), cols.map((c) => c.name), { blank: "None" });

  const s = state.schema.suggested;
  const pick = (id, fallback) => {
    const el = $(id), v = preset[id] ?? fallback ?? NONE;
    el.value = [...el.options].some((o) => o.value === v) ? v : el.options[0]?.value ?? NONE;
  };
  pick("x", s.x); pick("y", s.y); pick("color", s.color); pick("compare", s.compare);
  pick("hover", cols.find((c) => /cell|barcode|sample|donor|id$/i.test(c.name))?.name);

  $("dataset-meta").textContent =
    `${state.schema.n_rows.toLocaleString()} rows, ${cols.length} columns`;
  $("download").href = dsPath("download");
  const n = state.schema.n_rows;
  $("size").value = n < 1000 ? 8 : n < 10000 ? 5 : n < 100000 ? 3 : 2;

  // forest plot settings
  const f = state.schema.forest;
  const text = cols.filter((c) => !c.numeric).map((c) => c.name);
  fillSelect($("f-label"), [...text, ...numeric]);
  fillSelect($("f-est"), numeric);
  fillSelect($("f-lower"), numeric, { blank: "None" });
  fillSelect($("f-upper"), numeric, { blank: "None" });
  fillSelect($("f-se"), numeric, { blank: "None" });
  fillSelect($("f-p"), numeric, { blank: "None" });
  fillSelect($("f-group"), categorical, { blank: "None" });
  fillSelect($("f-panel"), categorical, { blank: "None" });
  pick("f-label", f.label); pick("f-est", f.estimate); pick("f-lower", f.lower); pick("f-upper", f.upper);
  pick("f-se", f.se); pick("f-p", f.p); pick("f-group", f.group); pick("f-panel", f.panel);
  $("f-ratio").checked = preset.ratio !== undefined ? preset.ratio === "1" : f.ratio;

  const views = ["embedding", "forest", "table"];
  $("view").value = views.includes(preset.view) ? preset.view : state.schema.kind;
  applyView();
  await renderAll();
}

function applyView() {
  const view = $("view").value;
  $("embedding-controls").hidden = view !== "embedding";
  $("forest-controls").hidden = view !== "forest";
  $("scatter-section").hidden = view !== "embedding";
  $("composition-section").hidden = view !== "embedding";
  $("forest-section").hidden = view !== "forest";
}

async function renderAll() {
  writeHash();
  const view = $("view").value;
  const jobs = [renderTable()];
  if (view === "embedding") jobs.push(renderScatter(), renderComposition());
  if (view === "forest") jobs.push(renderForest());
  document.body.classList.add("loading");
  await Promise.allSettled(jobs);
  document.body.classList.remove("loading");
}

// ------------------------------------------------------------ scatter
async function renderScatter() {
  const x = $("x").value, y = $("y").value, color = $("color").value, hover = $("hover").value;
  const el = $("scatter");
  if (!x || !y) { Plotly.purge(el); return; }
  let d;
  try { d = await api(dsPath("points", { x, y, color, hover })); }
  catch (e) { return toast(e.message); }

  $("scatter-title").textContent = `${x} vs ${y}`;
  $("scatter-note").textContent = d.sampled
    ? `Showing a random ${d.n_shown.toLocaleString()} of ${d.n_total.toLocaleString()} points`
    : `${d.n_total.toLocaleString()} points`;

  const size = Number($("size").value), opacity = Number($("opacity").value);
  const marker = { size, opacity, line: { width: 0 } };
  const hoverExtra = hover ? "<br>%{text}" : "";
  const colInfo = color ? column(color) : null;
  let traces;

  if (colInfo && colInfo.categorical) {
    const groups = new Map();
    d.color.forEach((v, i) => {
      const k = v ?? "(missing)";
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(i);
    });
    traces = naturalSort([...groups.keys()]).map((k, gi) => {
      const idx = groups.get(k);
      return {
        type: "scattergl", mode: "markers", name: String(k),
        x: idx.map((i) => d.x[i]), y: idx.map((i) => d.y[i]),
        text: hover ? idx.map((i) => d.hover[i]) : undefined,
        marker: { ...marker, color: swatch(gi) },
        hovertemplate: `<b>${color}: ${k}</b><br>${x}: %{x:.3g}<br>${y}: %{y:.3g}${hoverExtra}<extra></extra>`,
      };
    });
  } else {
    traces = [{
      type: "scattergl", mode: "markers", x: d.x, y: d.y,
      text: hover ? d.hover : undefined,
      marker: color
        ? { ...marker, color: d.color, colorscale: "Viridis", colorbar: { title: { text: color, side: "right" }, thickness: 12 } }
        : { ...marker, color: css("--hema") },
      hovertemplate: `${x}: %{x:.3g}<br>${y}: %{y:.3g}${color ? `<br>${color}: %{marker.color:.3g}` : ""}${hoverExtra}<extra></extra>`,
    }];
  }

  const layout = baseLayout();
  layout.xaxis.title = { text: x };
  layout.yaxis.title = { text: y };
  layout.legend.title = color ? { text: color } : undefined;
  layout.uirevision = `${state.dataset}|${x}|${y}`; // keep zoom when only styling changes
  Plotly.react(el, traces, layout, PLOT_CONFIG);
}

// -------------------------------------------------------- composition
async function renderComposition() {
  const group = $("color").value, compare = $("compare").value;
  const el = $("composition");
  const title = $("composition-title");
  const colInfo = group ? column(group) : null;

  if (!colInfo || !colInfo.categorical) {
    title.textContent = "Cluster composition";
    Plotly.purge(el);
    el.innerHTML = `<p class="note">Choose a cluster column under “Color points by” to see cluster sizes.</p>`;
    return;
  }
  el.innerHTML = "";
  let d;
  try { d = await api(dsPath("summary", { group, compare })); }
  catch (e) { return toast(e.message); }

  const pct = $("proportions").checked;
  const keys = Object.keys(d.series);
  const totals = d.groups.map((_, i) => keys.reduce((s, k) => s + d.series[k][i], 0));
  const grand = totals.reduce((a, b) => a + b, 0);
  const val = (v, i) => (pct ? (100 * v) / (compare ? totals[i] || 1 : grand || 1) : v);

  let traces;
  if (compare) {
    title.textContent = `${compare} within each ${group}`;
    traces = naturalSort(keys).map((k, ki) => ({
      type: "bar", name: k, x: d.groups.map(String),
      y: d.series[k].map(val), customdata: d.series[k],
      marker: { color: swatch(ki + 2) },
      hovertemplate: `${group} %{x}<br>${compare}: ${k}<br>%{customdata:,} rows${pct ? " (%{y:.1f}%)" : ""}<extra></extra>`,
    }));
  } else {
    title.textContent = `Size of each ${group}`;
    const counts = d.series.count;
    traces = [{
      type: "bar", x: d.groups.map(String), y: counts.map(val), customdata: counts,
      marker: { color: d.groups.map((_, i) => swatch(i)) },
      hovertemplate: `${group} %{x}<br>%{customdata:,} rows${pct ? " (%{y:.1f}% of all)" : ""}<extra></extra>`,
    }];
  }
  const layout = baseLayout();
  layout.barmode = compare ? "stack" : "group";
  layout.xaxis.type = "category";
  layout.xaxis.title = { text: group };
  layout.yaxis.title = { text: pct ? (compare ? `% of ${group}` : "% of all rows") : "Rows" };
  if (pct && compare) layout.yaxis.range = [0, 100];
  layout.legend.title = compare ? { text: compare } : undefined;
  layout.showlegend = !!compare;
  Plotly.react(el, traces, layout, PLOT_CONFIG);
}


// ------------------------------------------------------------- forest
const fmt = (v) => (v === null || v === undefined ? "–" : Math.abs(v) >= 0.01 && Math.abs(v) < 1e4 ? v.toFixed(2) : v.toPrecision(2));
const fmtP = (v) => (v === null || v === undefined ? "" : v < 1e-3 ? v.toExponential(1) : v.toPrecision(2));

async function renderForest() {
  const el = $("forest");
  const v = (id) => $(id).value || undefined;
  const params = {
    label: v("f-label"), estimate: v("f-est"), lower: v("f-lower"), upper: v("f-upper"),
    se: v("f-se"), p: v("f-p"), group: v("f-group"), panel: v("f-panel"), ratio: $("f-ratio").checked,
  };
  if (!params.label || !params.estimate) { Plotly.purge(el); return; }
  if (!(params.lower && params.upper) && !params.se) {
    Plotly.purge(el);
    el.innerHTML = `<p class="note">Choose lower and upper interval columns, or a standard error column, to draw the intervals.</p>`;
    $("forest-note").textContent = "";
    return;
  }
  el.innerHTML = "";
  let d;
  try { d = await api(dsPath("forest", params)); }
  catch (e) { return toast(e.message); }

  const ratio = params.ratio;
  const groups = d.group ? naturalSort([...new Set(d.group)]) : [null];
  const panels = d.panel ? [...new Set(d.panel)].slice(0, 4) : [null];
  const labels = d.labels;
  const nG = groups.length;
  const step = nG > 1 ? Math.min(0.7 / nG, 0.22) : 0;
  const pos = new Map(labels.map((l, i) => [l, labels.length - 1 - i])); // first row at the top
  const showSig = $("f-sig").checked && d.p;

  const traces = [];
  panels.forEach((pn, pi) => {
    groups.forEach((g, gi) => {
      const idx = d.est.map((_, i) => i).filter((i) =>
        (pn === null || d.panel[i] === pn) && (g === null || d.group[i] === g) && (!ratio || d.est[i] > 0));
      if (!idx.length) return;
      const color = nG > 1 ? swatch(gi) : css("--hema");
      const filled = idx.map((i) => !showSig || (d.p[i] !== null && d.p[i] < 0.05));
      traces.push({
        type: "scatter", mode: "markers",
        name: g ?? params.estimate, legendgroup: g ?? "all", showlegend: false,
        x: idx.map((i) => d.est[i]),
        y: idx.map((i) => pos.get(d.label[i]) + (nG > 1 ? (((nG - 1) / 2) - gi) * step : 0)),
        error_x: {
          type: "data", symmetric: false, thickness: 1.6, width: 0, color,
          array: idx.map((i) => (d.hi[i] ?? d.est[i]) - d.est[i]),
          arrayminus: idx.map((i) => d.est[i] - (d.lo[i] ?? d.est[i])),
        },
        marker: {
          size: 9, color: filled.map((f) => (f ? color : css("--surface"))),
          line: { color, width: 1.8 }, symbol: "square",
        },
        customdata: idx.map((i) => [d.label[i], fmt(d.lo[i]), fmt(d.hi[i]), d.p ? fmtP(d.p[i]) : ""]),
        hovertemplate: `<b>%{customdata[0]}</b>${g ? `<br>${params.group}: ${g}` : ""}${pn ? `<br>${params.panel}: ${pn}` : ""}` +
          `<br>${params.estimate}: %{x:.3g} (%{customdata[1]} to %{customdata[2]})` +
          `${d.p ? `<br>${params.p}: %{customdata[3]}` : ""}<extra></extra>`,
        xaxis: pi === 0 ? "x" : `x${pi + 1}`, yaxis: "y",
      });
    });
  });

  if (nG > 1) {
    groups.forEach((g, gi) => traces.push({
      type: "scatter", mode: "markers", x: [null], y: [null], name: g, legendgroup: g, hoverinfo: "skip",
      marker: { size: 9, symbol: "square", color: swatch(gi) },
    }));
  }

  const layout = baseLayout();
  const gap = 0.04, w = (1 - gap * (panels.length - 1)) / panels.length;
  const axisBase = { ...layout.xaxis, type: ratio ? "log" : "linear", zeroline: false };
  delete layout.xaxis;
  panels.forEach((pn, pi) => {
    const key = pi === 0 ? "xaxis" : `xaxis${pi + 1}`;
    layout[key] = { ...axisBase, domain: [pi * (w + gap), pi * (w + gap) + w], title: { text: params.estimate },
                    anchor: "y", ...(pi > 0 ? { matches: "x" } : {}) };
  });
  layout.yaxis = {
    ...layout.yaxis, tickvals: labels.map((l) => pos.get(l)), ticktext: labels, automargin: true,
    range: [-0.7, labels.length - 0.3], showgrid: false, zeroline: false,
  };
  const ref = ratio ? 1 : 0;
  layout.shapes = panels.map((_, pi) => ({
    type: "line", xref: pi === 0 ? "x" : `x${pi + 1}`, yref: "paper", x0: ref, x1: ref, y0: 0, y1: 1,
    line: { color: css("--muted"), width: 1, dash: "dot" },
  }));
  if (panels[0] !== null) {
    layout.annotations = panels.map((pn, pi) => ({
      text: `<b>${pn}</b>`, showarrow: false, xref: "paper", yref: "paper", yanchor: "bottom",
      x: pi * (w + gap) + w / 2, y: 1, font: { size: 13 },
    }));
    layout.margin = { ...layout.margin, t: 36 };
  }
  layout.legend = { ...layout.legend, title: params.group ? { text: params.group } : undefined, traceorder: "normal" };
  layout.hovermode = "closest";
  el.style.height = `${Math.max(320, labels.length * (nG > 2 ? 46 : nG > 1 ? 34 : 26) + 120)}px`;
  Plotly.react(el, traces, layout, PLOT_CONFIG);

  $("forest-title").textContent = `${params.estimate} by ${params.label}`;
  const notes = [`${d.n_rows.toLocaleString()} estimates.`];
  if (d.note) notes.push(d.note);
  if (d.n_dropped) notes.push(`${d.n_dropped} rows without an estimate are hidden.`);
  if (ratio && d.est.some((x) => x !== null && x <= 0)) notes.push("Estimates at or below 0 can’t be shown on a ratio scale.");
  if (d.panel && new Set(d.panel).size > 4) notes.push("Only the first 4 panels are shown.");
  if (d.truncated) notes.push("Only the first 2,000 rows are drawn.");
  if (showSig) notes.push("Hollow markers have p ≥ 0.05.");
  $("forest-note").textContent = notes.join(" ");
}

// -------------------------------------------------------------- table
async function renderTable() {
  let d;
  try {
    d = await api(dsPath("rows", { offset: state.offset, limit: state.limit, q: state.q, sort: state.sort, desc: state.sort ? state.desc : null }));
  } catch (e) { return toast(e.message); }

  const numericCols = new Set(state.schema.columns.filter((c) => c.numeric).map((c) => c.name));
  const thead = $("table").tHead, tbody = $("table").tBodies[0];
  thead.innerHTML = "";
  const tr = thead.insertRow();
  for (const c of d.columns) {
    const th = document.createElement("th");
    th.textContent = c;
    th.tabIndex = 0;
    th.scope = "col";
    if (state.sort === c) th.setAttribute("aria-sort", state.desc ? "descending" : "ascending");
    const sortBy = () => {
      if (state.sort === c) state.desc = !state.desc; else { state.sort = c; state.desc = false; }
      state.offset = 0;
      renderTable();
    };
    th.addEventListener("click", sortBy);
    th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sortBy(); } });
    tr.append(th);
  }

  tbody.innerHTML = "";
  if (!d.rows.length) {
    const cell = tbody.insertRow().insertCell();
    cell.colSpan = d.columns.length;
    cell.textContent = state.q ? `No rows contain “${state.q}”. Clear the filter to see all rows.` : "This table is empty.";
  }
  for (const row of d.rows) {
    const r = tbody.insertRow();
    row.forEach((v, i) => {
      const td = r.insertCell();
      td.textContent = v ?? "";
      if (numericCols.has(d.columns[i])) td.className = "num";
    });
  }

  const end = Math.min(state.offset + state.limit, d.n_matching);
  $("page-info").textContent = d.n_matching
    ? `Rows ${(state.offset + 1).toLocaleString()}–${end.toLocaleString()} of ${d.n_matching.toLocaleString()}`
    : "";
  $("prev").disabled = state.offset === 0;
  $("next").disabled = end >= d.n_matching;
}

// -------------------------------------------------------------- events
function wire() {
  $("dataset").addEventListener("change", (e) => loadDataset(e.target.value));
  for (const id of ["x", "y", "hover"]) $(id).addEventListener("change", () => { writeHash(); renderScatter(); });
  $("color").addEventListener("change", () => { writeHash(); renderScatter(); renderComposition(); });
  $("compare").addEventListener("change", () => { writeHash(); renderComposition(); });
  $("proportions").addEventListener("change", renderComposition);
  $("view").addEventListener("change", () => { applyView(); renderAll(); });
  for (const id of [...FOREST_IDS, "f-ratio", "f-sig"]) $(id).addEventListener("change", () => { writeHash(); renderForest(); });
  for (const id of ["size", "opacity"]) {
    $(id).addEventListener("input", () => {
      const el = $("scatter");
      if (el.data) Plotly.restyle(el, { "marker.size": Number($("size").value), "marker.opacity": Number($("opacity").value) });
    });
  }
  let t;
  $("search").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => { state.q = e.target.value.trim(); state.offset = 0; renderTable(); }, 250);
  });
  $("prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); renderTable(); });
  $("next").addEventListener("click", () => { state.offset += state.limit; renderTable(); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => state.schema && renderAll());
}

document.addEventListener("DOMContentLoaded", () => { wire(); init(); });
