"""Smoke tests against synthetic data:  pip install -r requirements-dev.txt && pytest"""
import importlib, os, subprocess, sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent
UMAP, OR, SHAP = "t1grs_cluster_umap.csv", "cluster_complications_or.tsv", "cluster_locus_shap_log2fc.tsv"

@pytest.fixture(scope="session")
def client(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    subprocess.run([sys.executable, ROOT / "make_sample_data.py", data], check=True, capture_output=True)
    os.environ["DATA_DIR"] = str(data)
    sys.path.insert(0, str(ROOT))
    import main
    importlib.reload(main)
    return TestClient(main.app)

def schema(client, name):
    return client.get(f"/api/datasets/{name}/schema").json()

def test_lists_datasets(client):
    names = {d["name"] for d in client.get("/api/datasets").json()["datasets"]}
    assert {UMAP, OR, SHAP} <= names

def test_embedding_detected(client):
    s = schema(client, UMAP)
    assert s["kind"] == "embedding"
    assert (s["suggested"]["x"], s["suggested"]["y"], s["suggested"]["color"], s["suggested"]["compare"]) == ("UMAP1", "UMAP2", "cluster", "status")

def test_forest_with_intervals_detected(client):
    s = schema(client, OR)
    f = s["forest"]
    assert s["kind"] == "forest" and f["ratio"]
    assert (f["estimate"], f["lower"], f["upper"], f["p"], f["label"], f["group"], f["panel"]) == \
        ("odds_ratio", "ci_lower", "ci_upper", "p_value", "complication", "cluster", "cohort")

def test_forest_from_se(client):
    f = schema(client, SHAP)["forest"]
    assert (f["estimate"], f["se"], f["label"], f["ratio"]) == ("log2FC", "se", "locus", False)
    d = client.get(f"/api/datasets/{SHAP}/forest", params={"label": "locus", "estimate": "log2FC", "se": "se"}).json()
    assert d["note"] and all(lo < e < hi for lo, e, hi in zip(d["lo"], d["est"], d["hi"]))

def test_forest_ratio_from_se_is_asymmetric(client):
    d = client.get(f"/api/datasets/{OR}/forest", params={"label": "complication", "estimate": "odds_ratio", "se": "p_value", "ratio": True}).json()
    assert "log scale" in d["note"]

def test_forest_needs_intervals(client):
    r = client.get(f"/api/datasets/{OR}/forest", params={"label": "complication", "estimate": "odds_ratio"})
    assert r.status_code == 400

def test_forest_keeps_file_order(client):
    d = client.get(f"/api/datasets/{OR}/forest", params={"label": "complication", "estimate": "odds_ratio", "lower": "ci_lower", "upper": "ci_upper"}).json()
    assert d["labels"] == ["Nephropathy", "Neuropathy", "Retinopathy", "Cardiovascular disease"]

def test_small_p_values_survive(client):
    rows = client.get(f"/api/datasets/{SHAP}/rows", params={"limit": 500, "sort": "p_value"}).json()["rows"]
    assert rows[0][4] > 0

def test_points_sampling(client):
    d = client.get(f"/api/datasets/{UMAP}/points", params={"x": "UMAP1", "y": "UMAP2", "max_points": 1000}).json()
    assert d["sampled"] and len(d["x"]) == 1000

def test_missing_values_are_null(client):
    rows = client.get(f"/api/datasets/{UMAP}/rows", params={"limit": 200}).json()["rows"]
    assert any(r[6] is None for r in rows)  # age_at_onset is empty for nondiabetic

def test_summary_crosstab(client):
    d = client.get(f"/api/datasets/{UMAP}/summary", params={"group": "cluster", "compare": "status"}).json()
    assert set(d["series"]) == {"T1D", "Nondiabetic"} and len(d["groups"]) == 4

@pytest.mark.parametrize("name", ["../../etc/passwd", "nope.csv", "%2e%2e/%2e%2e/etc/passwd"])
def test_rejects_unknown_files(client, name):
    assert client.get(f"/api/datasets/{name}/schema").status_code == 404

def test_unknown_column(client):
    assert client.get(f"/api/datasets/{UMAP}/points", params={"x": "nope", "y": "UMAP2"}).status_code == 400

@pytest.mark.parametrize("path,marker", [("/", "About T1GRS"), ("/explore", 'id="forest"')])
def test_pages(client, path, marker):
    r = client.get(path)
    assert r.status_code == 200 and marker in r.text

@pytest.mark.parametrize("path", ["/main.py", "/.env.example", "/README.md", "/test_app.py", "/check_data.py"])
def test_code_and_secrets_not_served(client, path):
    assert client.get(path).status_code == 404

@pytest.mark.parametrize("path", ["/app.js", "/home.js", "/style.css", "/vendor/plotly.min.js"])
def test_assets_served(client, path):
    assert client.get(path).status_code == 200
