from pathlib import Path
import os, struct, sys, tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="layervault-resin-preparation-")

from fastapi.testclient import TestClient
from app.main import app


def binary_stl(tris):
    out = bytearray(b"LayerVault resin preparation test".ljust(80, b"\0"))
    out += struct.pack("<I", len(tris))
    for a, b, c in tris:
        out += struct.pack("<12fH", 0, 0, 0, *a, *b, *c, 0)
    return bytes(out)


def box(x, y, z, off=(0, 0, 0)):
    ox, oy, oz = off
    v = [(ox, oy, oz), (ox+x, oy, oz), (ox+x, oy+y, oz), (ox, oy+y, oz),
         (ox, oy, oz+z), (ox+x, oy, oz+z), (ox+x, oy+y, oz+z), (ox, oy+y, oz+z)]
    f = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
         (1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    return [tuple(v[i] for i in q) for q in f]


def suction_cup_tris(n=20):
    tris = []
    def quad(a, b, c, d, flip=False):
        tris.extend([(a,c,b),(a,d,c)] if flip else [(a,b,c),(a,c,d)])
    for i in range(n):
        for j in range(n):
            x0=2+6*i/n; x1=2+6*(i+1)/n; y0=2+6*j/n; y1=2+6*(j+1)/n
            quad((x0,y0,10),(x1,y0,10),(x1,y1,10),(x0,y1,10),True)
    for k in range(n):
        z0=10*k/n; z1=10*(k+1)/n
        quad((2,2,z0),(2,8,z0),(2,8,z1),(2,2,z1))
        quad((8,8,z0),(8,2,z0),(8,2,z1),(8,8,z1))
        quad((8,2,z0),(2,2,z0),(2,2,z1),(8,2,z1))
        quad((2,8,z0),(8,8,z0),(8,8,z1),(2,8,z1))
    return tris


c = TestClient(app)
printer = c.post("/api/printers", json={
    "name":"40um Resin", "technology":"MSLA / Resin", "build_x":120, "build_y":68,
    "build_z":150, "resolution_x":3000, "resolution_y":1700,
    "xy_resolution_x_um":40, "xy_resolution_y_um":40,
}).json()

# A simple 0.20 mm exposed thin feature must become a verified child near the 0.50 mm target.
r = c.post("/api/models/upload", files={"file":("thin-feature.stl", binary_stl(box(10,10,.2)), "model/stl")}, data={"title":"Thin exposed feature"})
assert r.status_code == 200, r.text
feature_id = r.json()["model"]["id"]
before = c.get(f"/api/models/{feature_id}/health", params={"printer_id":printer["id"]}).json()
assert before["manufacturing"]["resin"]["preparation"]["can_thicken_broad_regions"] is True, before
prepared = c.post(f"/api/models/{feature_id}/manufacturing/repair", json={"printer_id":printer["id"], "target_thickness_mm":.5})
assert prepared.status_code == 200, prepared.text
payload = prepared.json()
assert payload.get("model") and payload["model"]["parent_model_id"] == feature_id, payload
assert payload["geometry_after"]["metrics"]["watertight"] is True
assert payload["geometry_after"]["metrics"]["boundary_edges"] == 0
assert payload["after"]["score"] >= payload["before"]["score"]
assert payload["improvements"]["broad_thin_regions"][1] < payload["improvements"]["broad_thin_regions"][0]
child_thickness = payload["after"]["thickness"]
assert child_thickness["estimated_p05_mm"] >= .45, child_thickness
source_again = c.get(f"/api/models/{feature_id}/health").json()
assert source_again["metrics"]["dimensions_mm"][2] == .2

# A downward cup is highlighted and the preparation pass may only accept an orientation that
# reduces the suction candidate count without increasing island risk.
r = c.post("/api/models/upload", files={"file":("cup.stl", binary_stl(suction_cup_tris()), "model/stl")}, data={"title":"Downward cup"})
assert r.status_code == 200, r.text
cup_id = r.json()["model"]["id"]
cup_before = c.get(f"/api/models/{cup_id}/health", params={"printer_id":printer["id"]}).json()["manufacturing"]
assert cup_before["resin"]["suction_pockets"]["candidate_count"] >= 1, cup_before
assert any(issue["code"] == "suction_pocket" and issue["markers"] for issue in cup_before["issues"])
cup_prepared = c.post(f"/api/models/{cup_id}/manufacturing/repair", json={"printer_id":printer["id"], "target_thickness_mm":.5})
assert cup_prepared.status_code == 200, cup_prepared.text
cup_payload = cup_prepared.json()
assert cup_payload.get("model"), cup_payload
assert cup_payload["improvements"]["suction_candidates"][1] < cup_payload["improvements"]["suction_candidates"][0]
assert cup_payload["improvements"]["island_candidates"][1] <= cup_payload["improvements"]["island_candidates"][0]

print("LayerVault resin preparation, 0.50 mm exposed-feature and suction-orientation regression: PASS")
