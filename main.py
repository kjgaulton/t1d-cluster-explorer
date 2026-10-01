"""T1D cluster explorer: serves CSV/TSV clustering results from DATA_DIR.

Data never lives in the repo. Point DATA_DIR at the directory on the server
that holds the result tables, e.g. DATA_DIR=/srv/t1d-data.
"""

from __future__ import annotations

import base64
import os
import re
import secrets
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import plotly
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).expanduser().resolve()
MAX_POINTS_DEFAULT = int(os.environ.get("MAX_POINTS", "100000"))
AUTH_USER = os.environ.get("BASIC_AUTH_USER")
AUTH_PASS = os.environ.get("BASIC_AUTH_PASS")

SUFFIXES = {".csv": ",", ".csv.gz": ",", ".tsv": "\t", ".tsv.gz": "\t", ".txt": "\t", ".txt.gz": "\t"}
CATEGORICAL_MAX_UNIQUE = 60

HERE = Path(__file__).parent
PLOTLY_JS = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"

app = FastAPI(title="T1D cluster explorer", docs_url="/api/docs", redoc_url=None)


# ---------------------------------------------------------------- auth ----
@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Optional HTTP basic auth, enabled when both env vars are set."""
    if not (AUTH_USER and AUTH_PASS) or request.url.path == "/api/health":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
            if secrets.compare_digest(user, AUTH_USER) and secrets.compare_digest(pw, AUTH_PASS):
                return await call_next(request)
        except Exception:
            pass
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="T1D cluster explorer"'})


# ------------------------------------------------------------- loading ----
def _separator(path: Path) -> str | None:
    name = path.name.lower()
    for suffix, sep in SUFFIXES.items():
        if name.endswith(suffix):
            return sep
    return None


def list_datasets() -> dict[str, Path]:
    """Map of relative name -> path for every table under DATA_DIR."""
    if not DATA_DIR.is_dir():
        return {}
    found = {}
    for path in sorted(DATA_DIR.rglob("*")):
        if path.is_file() and _separator(path) and not any(p.startswith(".") for p in path.relative_to(DATA_DIR).parts):
            found[path.relative_to(DATA_DIR).as_posix()] = path
    return found


@lru_cache(maxsize=16)
def _read(path_str: str, mtime: float) -> pd.DataFrame:
    path = Path(path_str)
    df = pd.read_csv(path, sep=_separator(path), low_memory=False)
    df.columns = [str(c).strip() or f"column_{i}" for i, c in enumerate(df.columns)]
    return df


def load(name: str) -> pd.DataFrame:
    datasets = list_datasets()
    if name not in datasets:  # membership check also blocks path traversal
        raise HTTPException(404, f"No dataset named '{name}' in the data directory.")
    path = datasets[name]
    try:
        return _read(str(path), path.stat().st_mtime)
    except Exception as exc:
        raise HTTPException(422, f"Could not read '{name}': {exc}") from exc


def require_columns(df: pd.DataFrame, *cols: str | None) -> None:
    missing = [c for c in cols if c and c not in df.columns]
    if missing:
        raise HTTPException(400, f"Unknown column(s): {', '.join(missing)}")


def to_list(series: pd.Series) -> list:
    """JSON-safe list: NaN/inf become null, numpy scalars become Python."""
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        arr = series.to_numpy(dtype=float, na_value=np.nan)
        return [None if not np.isfinite(v) else (int(v) if v.is_integer() and abs(v) < 2**53 else float(f"{v:.6g}")) for v in arr]
    return [None if pd.isna(v) else str(v) for v in series.tolist()]


# ------------------------------------------------------------ guessing ----
EMBED_PATTERNS = [r"umap", r"tsne|t_sne|t-sne", r"^pc|pca", r"phate", r"mds", r"emb", r"^x$|^y$", r"dim"]
CLUSTER_PATTERN = re.compile(r"cluster|leiden|louvain|subtype|endotype|cell_?type|label|group|class", re.I)


def describe(df: pd.DataFrame) -> list[dict]:
    cols = []
    for c in df.columns:
        s = df[c]
        numeric = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
        n_unique = int(s.nunique(dropna=True))
        cols.append({
            "name": c,
            "numeric": numeric,
            "n_unique": n_unique,
            "n_missing": int(s.isna().sum()),
            "categorical": (not numeric and n_unique <= max(CATEGORICAL_MAX_UNIQUE, 1))
                           or (numeric and n_unique <= 30 and bool(CLUSTER_PATTERN.search(c))),
        })
    return cols


def suggest(cols: list[dict]) -> dict:
    numeric = [c["name"] for c in cols if c["numeric"]]
    x = y = None
    embedding = False
    for pat in EMBED_PATTERNS:
        hits = [c for c in numeric if re.search(pat, c, re.I)]
        if len(hits) >= 2:
            x, y = hits[0], hits[1]
            embedding = True
            break
    if x is None and len(numeric) >= 2:
        x, y = numeric[0], numeric[1]
    cats = [c["name"] for c in cols if c["categorical"]]
    color = next((c for c in cats if CLUSTER_PATTERN.search(c)), cats[0] if cats else None)
    compare = None
    for pat in (r"condition|status|disease|diagnosis|phenotype", r"group|stage|cohort", r"donor|subject|patient"):
        compare = next((c for c in cats if c != color and re.search(pat, c, re.I)), None)
        if compare:
            break
    return {"x": x, "y": y, "color": color, "compare": compare, "embedding": embedding}


# ------------------------------------------------------- forest plots ----
EST_PATTERNS = [
    r"^(odds_?ratio|or)$", r"^(hazard_?ratio|hr)$", r"^(rr|risk_?ratio)$",
    r"^(beta|b|estimate|est|effect|effect_?size|coef|coefficient|mean_?diff)$",
    r"log2_?fc|logfc|lfc|log_?fold|fold_?change",
    r"^(odds_?ratio|or|hr|beta|estimate|effect)[_.]",
]
LOW_PATTERN = re.compile(r"lower|(^|[_.])lo(w)?($|[_.])|lcl|lci|ci_?l|l95|2\.5|[_.]l$", re.I)
UP_PATTERN = re.compile(r"upper|(^|[_.])up($|[_.])|(^|[_.])hi(gh)?($|[_.])|ucl|uci|ci_?u|ci_?h|u95|97\.5|[_.]u$", re.I)
SE_PATTERN = re.compile(r"^(se|stderr|std_?err|standard_?error)$|[_.]se$", re.I)
P_PATTERN = re.compile(r"^p$|p_?val|pvalue|p\.value|padj|p_adj|fdr|q_?val|^q$", re.I)
RATIO_PATTERN = re.compile(r"(^|[_.])(or|hr|rr)($|[_.])|ratio|odds|hazard", re.I)
LABEL_PATTERN = re.compile(r"outcome|trait|complication|variant|locus|loci|gene|snp|rsid|feature|term|"
                           r"label|name|phenotype|variable|endpoint|condition", re.I)
GROUP_PATTERN = re.compile(r"cluster|leiden|subtype|endotype|group|arm", re.I)
PANEL_PATTERN = re.compile(r"cohort|dataset|study|model|source|panel|analysis", re.I)


def suggest_forest(df: pd.DataFrame, cols: list[dict]) -> dict:
    numeric = [c["name"] for c in cols if c["numeric"]]
    text = [c["name"] for c in cols if not c["numeric"]]
    cats = [c["name"] for c in cols if c["categorical"]]
    est = next((c for pat in EST_PATTERNS for c in numeric if re.search(pat, c, re.I)), None)
    rest = [c for c in numeric if c != est]
    lower = next((c for c in rest if LOW_PATTERN.search(c)), None)
    upper = next((c for c in rest if UP_PATTERN.search(c) and c != lower), None)
    se = next((c for c in rest if SE_PATTERN.search(c)), None)
    pval = next((c for c in rest if P_PATTERN.search(c) and c not in (lower, upper)), None)
    group = next((c for c in cats if GROUP_PATTERN.search(c)), None)
    panel = next((c for c in cats if c != group and PANEL_PATTERN.search(c)), None)
    candidates = [c for c in text if c not in (group, panel)]
    label = next((c for c in candidates if LABEL_PATTERN.search(c)), candidates[0] if candidates else None)
    if label is None and group:  # e.g. one row per cluster
        label, group = group, None
    ratio = bool(est and RATIO_PATTERN.search(est))
    ready = bool(est and label and ((lower and upper) or se))
    return {"estimate": est, "lower": lower, "upper": upper, "se": se, "p": pval, "label": label,
            "group": group, "panel": panel, "ratio": ratio, "ready": ready}


# ------------------------------------------------------------------ api ----
@app.get("/api/health")
def health():
    return {"status": "ok", "data_dir_exists": DATA_DIR.is_dir(), "datasets": len(list_datasets())}


@app.get("/api/datasets")
def datasets():
    out = []
    for name, path in list_datasets().items():
        stat = path.stat()
        out.append({"name": name, "bytes": stat.st_size, "modified": stat.st_mtime})
    return {"data_dir": str(DATA_DIR) if not AUTH_USER else None, "datasets": out}


@app.get("/api/datasets/{name:path}/schema")
def schema(name: str):
    df = load(name)
    cols = describe(df)
    suggested = suggest(cols)
    forest = suggest_forest(df, cols)
    if suggested["embedding"]:
        kind = "embedding"
    elif forest["ready"]:
        kind = "forest"
    else:
        kind = "table"
    return {"name": name, "n_rows": len(df), "columns": cols, "kind": kind,
            "suggested": suggested, "forest": forest}


@app.get("/api/datasets/{name:path}/forest")
def forest(name: str, label: str, estimate: str, lower: str | None = None, upper: str | None = None,
           se: str | None = None, p: str | None = None, group: str | None = None, panel: str | None = None,
           ratio: bool = False, max_rows: int = Query(2000, ge=1, le=10000)):
    df = load(name)
    require_columns(df, label, estimate, lower, upper, se, p, group, panel)
    if not ((lower and upper) or se):
        raise HTTPException(400, "Choose lower and upper interval columns, or a standard error column.")
    est = pd.to_numeric(df[estimate], errors="coerce")
    note = None
    if lower and upper:
        lo, hi = pd.to_numeric(df[lower], errors="coerce"), pd.to_numeric(df[upper], errors="coerce")
    else:
        s_err = pd.to_numeric(df[se], errors="coerce")
        if ratio:
            with np.errstate(divide="ignore", invalid="ignore"):
                lo, hi = np.exp(np.log(est) - 1.96 * s_err), np.exp(np.log(est) + 1.96 * s_err)
            note = f"95% intervals computed from {se}, assumed to be on the log scale."
        else:
            lo, hi = est - 1.96 * s_err, est + 1.96 * s_err
            note = f"95% intervals computed as estimate ± 1.96 × {se}."
    keep = est.notna().to_numpy()
    n_dropped = int((~keep).sum())
    sub = pd.DataFrame({"label": df[label].astype("string").fillna("(missing)"), "est": est, "lo": lo, "hi": hi})
    if group:
        sub["group"] = df[group].astype("string").fillna("(missing)")
    if panel:
        sub["panel"] = df[panel].astype("string").fillna("(missing)")
    if p:
        sub["p"] = pd.to_numeric(df[p], errors="coerce")
    sub = sub[keep]
    truncated = len(sub) > max_rows
    sub = sub.iloc[:max_rows]
    out = {c: to_list(sub[c]) for c in sub.columns}
    return {"n_rows": len(sub), "n_dropped": n_dropped, "truncated": truncated, "note": note,
            "labels": list(dict.fromkeys(out["label"])),  # file order, as authors usually intend
            **out}


@app.get("/api/datasets/{name:path}/points")
def points(name: str, x: str, y: str, color: str | None = None, hover: str | None = None,
           max_points: int = Query(MAX_POINTS_DEFAULT, ge=100, le=1_000_000)):
    df = load(name)
    require_columns(df, x, y, color, hover)
    sub = df
    sampled = False
    if len(df) > max_points:
        sub = df.sample(n=max_points, random_state=0)
        sampled = True
    payload = {"n_total": len(df), "n_shown": len(sub), "sampled": sampled,
               "x": to_list(sub[x]), "y": to_list(sub[y])}
    if color:
        payload["color"] = to_list(sub[color])
    if hover:
        payload["hover"] = to_list(sub[hover])
    return payload


@app.get("/api/datasets/{name:path}/summary")
def summary(name: str, group: str, compare: str | None = None):
    df = load(name)
    require_columns(df, group, compare)
    g = df[group].astype("string").fillna("(missing)")
    if compare:
        c = df[compare].astype("string").fillna("(missing)")
        table = pd.crosstab(g, c)
    else:
        table = g.value_counts().to_frame("count")
    table = table.sort_index(key=_natural_key)
    return {"groups": table.index.tolist(), "series": {str(k): table[k].astype(int).tolist() for k in table.columns}}


def _natural_key(idx: pd.Index) -> pd.Index:
    """Sort '2' before '10' when cluster labels are numbers stored as text."""
    num = pd.to_numeric(idx, errors="coerce")
    return pd.Index(num) if num.notna().all() else idx.str.lower()


@app.get("/api/datasets/{name:path}/rows")
def rows(name: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
         q: str | None = None, sort: str | None = None, desc: bool = False):
    df = load(name)
    require_columns(df, sort)
    view = df
    if q:
        mask = np.zeros(len(df), dtype=bool)
        for c in df.columns:
            mask |= df[c].astype("string").str.contains(q, case=False, regex=False, na=False).to_numpy()
        view = df[mask]
    if sort:
        view = view.sort_values(sort, ascending=not desc, na_position="last", kind="stable")
    page = view.iloc[offset: offset + limit]
    return {"n_matching": len(view), "offset": offset, "columns": list(df.columns),
            "rows": [list(r) for r in zip(*(to_list(page[c]) for c in df.columns))] if len(page) else []}


@app.get("/api/datasets/{name:path}/download")
def download(name: str):
    datasets = list_datasets()
    if name not in datasets:
        raise HTTPException(404, f"No dataset named '{name}'.")
    return FileResponse(datasets[name], filename=Path(name).name)


@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)


# --------------------------------------------------------------- pages ----
@app.get("/vendor/plotly.min.js", include_in_schema=False)
def plotly_js():
    return FileResponse(PLOTLY_JS, media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=604800"})


# Only these files are served. Everything else in this folder (main.py, .env, ...) stays private.
PAGES = {"": "index.html", "explore": "explore.html"}
ASSETS = {"app.js": "application/javascript", "home.js": "application/javascript", "style.css": "text/css"}


@app.get("/", include_in_schema=False)
@app.get("/explore", include_in_schema=False)
def page(request: Request):
    return FileResponse(HERE / PAGES[request.url.path.strip("/")], media_type="text/html")


@app.get("/{asset}", include_in_schema=False)
def asset(asset: str):
    if asset not in ASSETS:
        raise HTTPException(404, "Not found.")
    return FileResponse(HERE / asset, media_type=ASSETS[asset])
