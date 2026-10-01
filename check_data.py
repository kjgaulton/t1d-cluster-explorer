"""Check result tables before viewing them in the app.

    python check_data.py ./data
    python check_data.py /srv/t1d-data

Reports, for each file, what the explorer will detect (axes, cluster column,
comparison column) and flags problems. Nothing is changed.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
data_dir = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DATA_DIR", "data")).expanduser().resolve()
os.environ["DATA_DIR"] = str(data_dir)
sys.path.insert(0, str(ROOT))

from main import describe, list_datasets, load, suggest, suggest_forest  # noqa: E402

OK, WARN, FAIL = "  ok   ", "  check", "  FIX  "


def check(name):
    print(f"\n{name}")
    try:
        df = load(name)
    except Exception as exc:
        print(f"{FAIL} Could not read the file: {getattr(exc, 'detail', exc)}")
        return False

    cols = describe(df)
    s = suggest(cols)
    good = True
    print(f"{OK} {len(df):,} rows, {len(df.columns)} columns")

    if len(df.columns) == 1:
        sep = "tab" if name.lower().endswith((".csv", ".csv.gz")) else "comma"
        print(f"{FAIL} Only one column was found. The file may be {sep}-separated; "
              f"rename it to .{'tsv' if sep == 'tab' else 'csv'} so it is split correctly.")
        return False
    if len(df) == 0:
        print(f"{FAIL} The file has a header but no rows.")
        return False

    dupes = [c for c in df.columns if "." in c and c.rsplit(".", 1)[0] in df.columns]
    if dupes:
        print(f"{WARN} Repeated column names were renamed: {', '.join(dupes)}")
    unnamed = [c for c in df.columns if c.startswith(("Unnamed:", "column_"))]
    if unnamed:
        print(f"{WARN} Columns without a header name: {', '.join(unnamed)} "
              "(often a saved row index; harmless, but you can drop it)")

    f = suggest_forest(df, cols)
    if not s["embedding"] and f["ready"]:
        print(f"{OK} Shown as: forest plot")
        print(f"{OK} One row per {f['label']}; estimate {f['estimate']}"
              f"{' (ratio scale, log axis)' if f['ratio'] else ''}")
        if f["lower"] and f["upper"]:
            print(f"{OK} Intervals: {f['lower']} to {f['upper']}")
        else:
            print(f"{WARN} No interval columns found; intervals will be computed from {f['se']} "
                  f"({'assumed log scale' if f['ratio'] else 'estimate ± 1.96 × SE'}).")
        print(f"{OK if f['p'] else WARN} P-value: {f['p'] or 'none found (markers will all be filled)'}")
        if f["group"]:
            print(f"{OK} Colored by {f['group']}: {', '.join(map(str, df[f['group']].dropna().unique()[:6]))}")
        if f["panel"]:
            print(f"{OK} Split into panels by {f['panel']}: {', '.join(map(str, df[f['panel']].dropna().unique()[:4]))}")
        n_labels = df[f["label"]].nunique()
        if n_labels > 150:
            print(f"{WARN} {n_labels} distinct rows makes a very tall plot; consider filtering the file.")
        return good
    if f["estimate"] and not f["ready"] and not s["embedding"]:
        print(f"{WARN} Found an estimate column ({f['estimate']}) but no interval or SE columns. Name them "
              "e.g. ci_lower/ci_upper or se to get a forest plot.")

    if s["x"] and s["y"]:
        print(f"{OK if s['embedding'] else WARN} Shown as: {'embedding scatter plot' if s['embedding'] else 'table (scatter available)'}")
        how = "embedding columns" if s["embedding"] else "first two numeric columns (no UMAP/PCA-style names found)"
        print(f"{OK if s['embedding'] else WARN} Plot axes: {s['x']} vs {s['y']}  [{how}]")
    else:
        print(f"{WARN} Fewer than two numeric columns, so no scatter plot. The table and cluster chart still work.")

    if s["color"]:
        col = df[s["color"]]
        counts = col.value_counts(dropna=False)
        labels = ", ".join(f"{k} ({v:,})" for k, v in counts.head(8).items())
        print(f"{OK} Cluster column: {s['color']}  ->  {labels}{' …' if len(counts) > 8 else ''}")
        if col.isna().any():
            print(f"{WARN} {int(col.isna().sum()):,} rows have no cluster label; they appear as “(missing)”.")
        labels_set = {str(v).removesuffix(".0") for v in col.dropna().unique()}
        if labels_set and labels_set <= {"1", "2", "3", "4"}:
            print(f"{WARN} Clusters are numbered 1-4. In the paper, 1 is T cell-enriched, 2 MHC-enriched, "
                  "3 pancreas-enriched and 4 MHC-driven. The explorer shows the numbers unless you add names.")
        elif labels_set and labels_set <= {"0", "1", "2", "3"}:
            print(f"{WARN} Clusters are numbered 0-3 (ScanPy's default). The paper numbers them 1-4, so check "
                  "which label is which before naming them.")
    else:
        print(f"{WARN} No cluster column detected. Name it with 'cluster', 'leiden', or 'subtype', "
              "or pick it under “Color points by”.")

    if s["compare"]:
        print(f"{OK} Comparison column: {s['compare']}  ({df[s['compare']].nunique()} groups)")

    heavy = [c["name"] for c in cols if c["n_missing"] > 0.5 * len(df)]
    if heavy:
        print(f"{WARN} Mostly empty columns: {', '.join(heavy)}")
    return good


def main():
    print(f"Checking {data_dir}")
    if not data_dir.is_dir():
        print(f"{FAIL} This folder does not exist. Pass the folder that holds your result files.")
        sys.exit(1)
    names = list(list_datasets())
    if not names:
        others = [p.name for p in data_dir.iterdir() if p.is_file()][:10]
        print(f"{FAIL} No .csv, .tsv or .txt files found here.")
        if others:
            print(f"        Files present: {', '.join(others)}. Export them as CSV or TSV.")
        sys.exit(1)
    sample = {"t1grs_cluster_umap.csv", "cluster_complications_or.tsv", "cluster_locus_shap_log2fc.tsv",
              "islet_cells_umap.csv", "donor_endotypes.tsv", "cluster_markers.tsv"} & set(names)
    if sample:
        print(f"{WARN} Synthetic sample files are still here: {', '.join(sorted(sample))}. Delete them before real use.")
    results = [check(n) for n in names]
    print(f"\n{sum(results)} of {len(results)} files ready to view.")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
