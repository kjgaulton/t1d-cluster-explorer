# T1D cluster explorer

An interactive site for the four genetic clusters of type 1 diabetes defined by **T1GRS**, a machine-learning genetic risk score ([McGrail et al., *Nature Genetics* 2026](https://www.nature.com/articles/s41588-026-02578-y); model code at [Gaulton-Lab/t1grs](https://github.com/Gaulton-Lab/t1grs)).

- `/` is the homepage: an introduction, an explanation of T1GRS, the four clusters, the methods, the result tables on the server (with a live preview of a cluster plot), and citation and code links.
- `/explore` is the explorer: embeddings (UMAP, t-SNE, PCA), cluster sizes, cluster composition by group, and a searchable, sortable table.

## Editing the homepage text

All homepage copy lives in `index.html`. The T1GRS, cluster and methods text summarizes the Nature Genetics paper, so update it there if the analysis changes.

This repository contains **code only**. The app reads CSV/TSV files from a directory on the server (`DATA_DIR`), and the `.gitignore` plus a CI check keep data files out of git.

## How your data should look

Any `.csv`, `.tsv`, `.txt` (tab-separated), or gzipped version of these, with a header row. Subfolders work too. The explorer chooses a view for each file from its columns, and you can switch views in the sidebar.

**Embedding** (one row per person): shown as a scatter plot with a cluster-composition chart.

| Kind of column | Detected by | Used for |
|---|---|---|
| Coordinates | numeric names containing `umap`, `tsne`, `pc`, `phate`, ... | Axes |
| Cluster labels | names containing `cluster`, `leiden`, `subtype`, `endotype` | Point colors and composition chart |
| Comparison groups | names containing `status`, `condition`, `diagnosis`, `cohort` | Stacked composition chart |

**Effect sizes** (one row per estimate): shown as a forest plot, such as odds ratios of complications by cluster or per-locus SHAP fold changes.

| Kind of column | Detected by | Used for |
|---|---|---|
| Estimate | `odds_ratio`/`or`, `hr`, `beta`, `estimate`, `effect`, `log2FC`, ... | Marker position |
| Interval | names with `lower`/`upper`, `ci_lower`/`ci_upper`, `lcl`/`ucl`, `l95`/`u95`, `2.5`/`97.5` | Whiskers |
| Standard error (alternative) | `se`, `stderr`, `*_se` | Whiskers as ±1.96 SE (on the log scale for ratios) |
| P-value (optional) | `p`, `pvalue`, `p_value`, `padj`, `fdr` | Hollow markers when p ≥ 0.05 |
| Row label | text columns such as `complication`, `outcome`, `locus`, `gene`, `variant` | One row of the plot per value, in file order |
| Color group (optional) | `cluster`, `subtype`, `group` | Colored, offset markers |
| Panels (optional) | `cohort`, `dataset`, `study`, `model` | Side-by-side panels on a shared axis |

Ratio estimates (names with OR, HR, RR, "ratio") get a log axis with a reference line at 1; others use a linear axis with the line at 0.

There are no required file names: each file becomes one dataset. To check your files before viewing them, run:

```bash
python check_data.py /path/to/your/data
```

It reports, for each file, the plot axes, cluster column and comparison column the app will use, and flags problems such as the wrong separator, unnamed columns, or leftover sample files. It changes nothing.

Every choice can be changed in the sidebar. The current view is stored in the page URL, so you can send a colleague a link to an exact view.

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python make_sample_data.py          # synthetic tables in ./data (git-ignored)
DATA_DIR=./data uvicorn main:app --reload
# open http://localhost:8000     API docs: http://localhost:8000/api/docs
pytest                                       # run the tests
```

## Deploy on AWS EC2

**1. Launch an instance.** Ubuntu 24.04, `t3.small` or larger (pick more memory for tables over a few million rows; each loaded table is cached in RAM). In the security group, allow SSH (22) from your IP only, and HTTP/HTTPS (80/443) from the IP ranges that should see the site, such as your institution's network.

**2. Install the basics and get the code.**
```bash
sudo apt update && sudo apt install -y nginx git docker.io docker-compose-v2
sudo usermod -aG docker ubuntu && newgrp docker
git clone https://github.com/<you>/t1d-cluster-explorer.git && cd t1d-cluster-explorer
```

**3. Put the data on the server**, outside the repo folder:
```bash
sudo mkdir -p /srv/t1d-data && sudo chown ubuntu /srv/t1d-data
# from your computer:
scp results/*.csv ubuntu@<instance-ip>:/srv/t1d-data/
# or from S3:
aws s3 sync s3://<bucket>/t1d-results /srv/t1d-data
```

**4. Configure and start.**
```bash
cp .env.example .env && nano .env            # set BASIC_AUTH_USER / BASIC_AUTH_PASS
HOST_DATA_DIR=/srv/t1d-data docker compose up -d --build
```
Prefer no Docker? Create a venv in the repo folder, `pip install -r requirements.txt`, and use `t1d-explorer.service` with systemd.

**5. Put nginx in front.** Follow the comments at the top of `nginx.conf`. With a domain name, add HTTPS using `certbot --nginx`. Use HTTPS whenever a password is set, so it isn't sent in plain text.

**Check it:** `curl localhost:8000/api/health` should report the number of datasets found.

## Updating

- **New or changed data:** copy files into `/srv/t1d-data`. The app picks them up on the next page load with no restart, because files are re-read when they change.
- **New code:** `git pull && docker compose up -d --build`, or `sudo systemctl restart t1d-explorer`.

## Access and data protection

If the tables contain participant-level information, restrict who can reach the site. Use the security group to limit access to known IP ranges, and set `BASIC_AUTH_USER` and `BASIC_AUTH_PASS`. Check what your data use agreement or IRB requires for hosting on AWS. The container mounts the data directory read-only, and the app only serves files inside `DATA_DIR`.

## Layout

All code sits in this one folder:

```
main.py                 Server: reads the tables in DATA_DIR and serves the pages
index.html, home.js     Homepage
explore.html, app.js    Explorer (scatter, composition and forest plots, table)
style.css               Shared styles
check_data.py           Checks your data files before viewing
make_sample_data.py     Writes synthetic test data
test_app.py             Tests (run automatically on GitHub)
Dockerfile, docker-compose.yml, nginx.conf, t1d-explorer.service   Deployment
.github/workflows/      GitHub's required location for the automatic tests
data/                   Your result files (git-ignored; optional, see DATA_DIR)
```

The server only serves the page files listed in `main.py`, so code and `.env` in this folder are never reachable from a browser.
