"""Write SYNTHETIC example tables for local testing. Not real T1GRS results.

    python make_sample_data.py            # writes to ./data
    python make_sample_data.py /tmp/demo  # or anywhere else

Shapes mirror the real outputs: one embedding table (one row per person) and
effect-size tables for forest plots (one row per estimate).
"""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
out = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
out.mkdir(parents=True, exist_ok=True)

CLUSTERS = ["T cell-enriched", "MHC-enriched", "Pancreas-enriched", "MHC-driven"]

# 1. Embedding: UMAP of per-person SHAP profiles --------------------------------
centres = {"T cell-enriched": (-4, 2), "MHC-enriched": (3, 4), "Pancreas-enriched": (-1, -4), "MHC-driven": (5, -2)}
n = 6000
cluster = rng.choice(CLUSTERS, size=n, p=[0.27, 0.24, 0.22, 0.27])
status = rng.choice(["T1D", "Nondiabetic"], size=n, p=[0.34, 0.66])
umap = np.array([centres[c] for c in cluster]) + rng.normal(0, 1.3, (n, 2))
grs = np.clip(np.where(status == "T1D", rng.beta(6, 2, n), rng.beta(2, 6, n))
              - np.where(cluster == "Pancreas-enriched", 0.08, 0) + np.where(np.char.startswith(cluster.astype(str), "MHC"), 0.05, 0), 0, 1)
onset = np.where(status == "T1D",
                 rng.normal(np.where(np.char.startswith(cluster.astype(str), "MHC"), 11, 15), 6), np.nan).clip(1, 70).round(1)
pd.DataFrame({
    "individual_id": [f"ID{i:05d}" for i in range(n)],
    "UMAP1": umap[:, 0].round(4), "UMAP2": umap[:, 1].round(4),
    "cluster": cluster, "status": status,
    "t1grs_score": grs.round(4), "age_at_onset": onset,
}).to_csv(out / "t1grs_cluster_umap.csv", index=False)

# 2. Forest: odds ratios of complications by cluster, two cohorts ---------------
rows = []
for cohort in ["Discovery", "All of Us"]:
    for comp in ["Nephropathy", "Neuropathy", "Retinopathy", "Cardiovascular disease"]:
        for c in CLUSTERS:
            log_or = rng.normal(0.25 if c == "Pancreas-enriched" else -0.05, 0.08)
            se = rng.uniform(0.06, 0.12) * (1.8 if cohort == "All of Us" else 1)
            z = log_or / se
            rows.append({"cohort": cohort, "complication": comp, "cluster": c,
                         "odds_ratio": round(float(np.exp(log_or)), 3),
                         "ci_lower": round(float(np.exp(log_or - 1.96 * se)), 3),
                         "ci_upper": round(float(np.exp(log_or + 1.96 * se)), 3),
                         "p_value": float(f"{math.erfc(abs(z) / math.sqrt(2)):.3g}")})
pd.DataFrame(rows).to_csv(out / "cluster_complications_or.tsv", sep="\t", index=False)

# 3. Forest from standard errors: per-locus SHAP fold change by cluster -------
loci = ["HLA-DQB1 aa57", "HLA-DRB1 aa13", "HLA-B*39:06", "HLA-A*24:02", "INS", "PTPN22", "IL2RA",
        "IFIH1", "CTLA4", "TYK2", "CTRB2", "GLIS3"]
favoured = {"MHC-driven": {"HLA-DQB1 aa57", "HLA-DRB1 aa13"}, "MHC-enriched": {"HLA-B*39:06", "HLA-A*24:02"},
            "T cell-enriched": {"PTPN22", "IL2RA", "CTLA4"}, "Pancreas-enriched": {"INS", "CTRB2", "GLIS3"}}
rows = []
for locus in loci:
    for c in CLUSTERS:
        lfc = rng.normal(1.2 if locus in favoured[c] else -0.2, 0.25)
        se = rng.uniform(0.08, 0.2)
        rows.append({"locus": locus, "cluster": c, "log2FC": round(float(lfc), 3), "se": round(float(se), 3),
                     "p_value": float(f"{math.erfc(abs(lfc / se) / math.sqrt(2)):.3g}")})
pd.DataFrame(rows).to_csv(out / "cluster_locus_shap_log2fc.tsv", sep="\t", index=False)

print(f"Wrote synthetic tables to {out.resolve()}:")
for p in sorted(out.iterdir()):
    print(f"  {p.name}  ({p.stat().st_size / 1e3:.0f} kB)")
