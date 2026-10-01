"use strict";

// Same palette as the explorer (app.js) so clusters keep their colors across pages.
const PALETTE = [
  "#3A3F9E", "#C2457E", "#2A9D8F", "#E9A23B", "#6C8EBF", "#8E5572", "#4E9F3D", "#D1603D",
  "#7A6FB0", "#3F7F93", "#B5838D", "#A0A83B", "#5E548E", "#E07A5F", "#2F6690", "#9C6644",
  "#43AA8B", "#C9A227", "#8D99AE", "#BC4B51",
];
const PREFERRED = /t1grs|grs|genetic|geno|cluster/i;
const $ = (id) => document.getElementById(id);
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const swatch = (i) => (i === 0 ? css("--hema") : i === 1 ? css("--eosin") : PALETTE[i % PALETTE.length]);
const dsUrl = (name, suffix, params = {}) =>
  `/api/datasets/${name.split("/").map(encodeURIComponent).join("/")}/${suffix}?${new URLSearchParams(params)}`;

async function api(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

function naturalSort(values) {
  return [...values].sort((a, b) => String(a).localeCompare(String(b), undefined, { numeric: true }));
}

// ------------------------------------------------------------ dataset list
async function loadResults() {
  const list = $("dataset-list");
  let datasets;
  try {
    ({ datasets } = await api("/api/datasets"));
  } catch {
    list.innerHTML = `<li class="note">Results could not be loaded. Check that the server is running.</li>`;
    return [];
  }
  if (!datasets.length) {
    list.innerHTML = `<li class="note">No results have been added yet. Tables placed in the server’s data directory will appear here.</li>`;
    return [];
  }

  const schemas = await Promise.all(
    datasets.slice(0, 12).map((d) => api(dsUrl(d.name, "schema")).then((s) => ({ ...d, schema: s })).catch(() => ({ ...d })))
  );
  list.innerHTML = "";
  for (const d of schemas) {
    const li = document.createElement("li");
    const s = d.schema;
    let detail = "Could not be read";
    if (s && s.kind === "embedding") {
      detail = `Embedding of ${s.n_rows.toLocaleString()} rows${s.suggested.color ? `, colored by ${s.suggested.color}` : ""}`;
    } else if (s && s.kind === "forest") {
      detail = `Forest plot of ${s.n_rows.toLocaleString()} ${s.forest.estimate} estimates${s.forest.group ? ` by ${s.forest.group}` : ""}`;
    } else if (s) {
      detail = `Table of ${s.n_rows.toLocaleString()} rows`;
    }
    li.innerHTML = `<a href="/explore#dataset=${encodeURIComponent(d.name)}"><span class="ds-name"></span><span class="ds-detail"></span></a>`;
    li.querySelector(".ds-name").textContent = d.name;
    li.querySelector(".ds-detail").textContent = detail;
    list.append(li);
  }
  if (datasets.length > 12) {
    const li = document.createElement("li");
    li.innerHTML = `<a href="/explore"><span class="ds-name">${datasets.length - 12} more</span><span class="ds-detail">Browse all in the explorer</span></a>`;
    list.append(li);
  }
  return schemas;
}

// ------------------------------------------------------------ hero preview
let preview = null;

async function loadHero(schemas) {
  const candidates = schemas
    .filter((d) => d.schema && d.schema.kind === "embedding")
    // Prefer T1GRS-like names, then larger tables.
    .sort((a, b) =>
      (PREFERRED.test(b.name) - PREFERRED.test(a.name)) ||
      (b.schema.n_rows - a.schema.n_rows));
  const pick = candidates[0];
  if (!pick) return;

  const { x, y, color } = pick.schema.suggested;
  const params = { x, y, max_points: 6000 };
  if (color) params.color = color;
  try {
    const pts = await api(dsUrl(pick.name, "points", params));
    const cats = color ? naturalSort(new Set(pts.color.map((v) => v ?? "(missing)"))) : [];
    preview = { pts, cats: new Map(cats.map((c, i) => [c, i])) };
  } catch { return; }

  $("hero-figure").hidden = false;
  $("hero-link").href = `/explore#dataset=${encodeURIComponent(pick.name)}`;
  $("hero-caption").textContent = color
    ? `${pick.name}, colored by ${color}. Select the plot to explore it.`
    : `${pick.name}. Select the plot to explore it.`;
  draw();
}

function draw() {
  if (!preview) return;
  const canvas = $("hero-canvas");
  const dpr = window.devicePixelRatio || 1;
  const { width, height } = canvas.getBoundingClientRect();
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);

  const { pts, cats } = preview;
  const xs = pts.x.filter(Number.isFinite), ys = pts.y.filter(Number.isFinite);
  if (!xs.length) return;
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  const pad = 14;
  const scale = Math.min((width - 2 * pad) / (x1 - x0 || 1), (height - 2 * pad) / (y1 - y0 || 1));
  const ox = (width - (x1 - x0) * scale) / 2, oy = (height - (y1 - y0) * scale) / 2;
  const r = pts.n_shown < 1000 ? 3 : pts.n_shown < 4000 ? 1.8 : 1.3;
  const colors = [...cats.keys()].map((_, i) => swatch(i));
  const fallback = css("--hema");

  ctx.globalAlpha = 0.7;
  for (let i = 0; i < pts.x.length; i++) {
    const px = pts.x[i], py = pts.y[i];
    if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
    ctx.fillStyle = pts.color ? colors[cats.get(pts.color[i] ?? "(missing)")] : fallback;
    ctx.beginPath();
    ctx.arc(ox + (px - x0) * scale, height - (oy + (py - y0) * scale), r, 0, Math.PI * 2);
    ctx.fill();
  }
}

let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(draw, 150); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);

function wireCitation() {
  const btn = $("copy-citation");
  btn.addEventListener("click", async () => {
    const text = $("citation-text").textContent.replace(/\s+/g, " ").trim();
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = "Citation copied";
    } catch {
      getSelection().selectAllChildren($("citation-text"));
      btn.textContent = "Press Ctrl+C or Cmd+C to copy";
    }
    setTimeout(() => (btn.textContent = "Copy citation"), 2500);
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  wireCitation();
  const schemas = await loadResults();
  await loadHero(schemas);
});
