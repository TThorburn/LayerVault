from pathlib import Path
import os, re, sys, tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
source = Path(os.environ.get("BLUEBELL_STL", ""))
if not source.is_file():
    raise SystemExit("Set BLUEBELL_STL to the supplied, topology-repaired Bluebell STL")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="layervault-bluebell-resin-")

from fastapi.testclient import TestClient
from app.main import app


c = TestClient(app)
printer = c.post("/api/printers", json={
    "name":"Photon M3", "technology":"MSLA / Resin", "build_x":163.84, "build_y":102.4,
    "build_z":180, "resolution_x":4096, "resolution_y":2560,
    "xy_resolution_x_um":40, "xy_resolution_y_um":40,
}).json()
with source.open("rb") as handle:
    uploaded = c.post("/api/models/upload", files={"file":("Bluebell.stl", handle, "model/stl")}, data={"title":"Bluebell"})
assert uploaded.status_code == 200, uploaded.text
model_id = uploaded.json()["model"]["id"]
before = c.get(f"/api/models/{model_id}/health", params={"printer_id":printer["id"]}).json()
assert before["score"] == 100 and before["metrics"]["watertight"] is True, before
manufacturing_before = before["manufacturing"]
thin_issue = next((issue for issue in manufacturing_before["issues"] if issue["code"] == "thin_exposed_feature"), None)
assert thin_issue and len(thin_issue["markers"]) >= 5, manufacturing_before
visible_copy = " ".join([manufacturing_before["summary"], *manufacturing_before["recommendations"], *[f"{issue['title']} {issue['detail']}" for issue in manufacturing_before["issues"]]]).lower()
assert not re.search(r"\bwings?\b|\bmembranes?\b", visible_copy), visible_copy
before_regions = manufacturing_before["thickness"]["broad_thin_regions"]
assert len(before_regions) == 1 and before_regions[0]["estimated_sheet_area_mm2"] > 30, before_regions
prepared = c.post(f"/api/models/{model_id}/manufacturing/repair", json={"printer_id":printer["id"], "target_thickness_mm":.5})
assert prepared.status_code == 200, prepared.text
payload = prepared.json()
assert payload.get("model"), payload
assert payload["geometry_after"]["score"] == 100
assert payload["geometry_after"]["metrics"]["watertight"] is True
assert payload["after"]["score"] > payload["before"]["score"]
assert payload["improvements"]["broad_thin_regions"][1] < payload["improvements"]["broad_thin_regions"][0]
assert payload["improvements"]["island_candidates"][1] <= payload["improvements"]["island_candidates"][0]
assert payload["after"]["resin"]["preparation"]["can_thicken_broad_regions"] is False
after_regions = payload["after"]["thickness"]["broad_thin_regions"]
assert after_regions and after_regions[0]["estimated_p25_mm"] >= before_regions[0]["estimated_p25_mm"] + .08, (before_regions, after_regions)
assert payload["model"]["parent_model_id"] == model_id
assert any("0.50 mm" in action for action in payload["actions"])
source_after = c.get(f"/api/models/{model_id}/health").json()
assert source_after["score"] == 100 and source_after["metrics"]["watertight"] is True

print("LayerVault supplied Bluebell exposed-feature targeting and resin-preparation API regression: PASS")
