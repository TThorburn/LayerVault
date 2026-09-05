from pathlib import Path
import os
import struct
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="layervault-workshop-cad-")

from fastapi.testclient import TestClient
from app.main import app


def cube_stl(size: float = 10.0) -> bytes:
    v = [(0., 0., 0.), (size, 0., 0.), (size, size, 0.), (0., size, 0.),
         (0., 0., size), (size, 0., size), (size, size, size), (0., size, size)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    out = bytearray(b"LayerVault Workshop cube".ljust(80, b"\0"))
    out += struct.pack("<I", len(faces))
    for face in faces:
        a, b, c = (v[i] for i in face)
        out += struct.pack("<12fH", 0., 0., 0., *a, *b, *c, 0)
    return bytes(out)


client = TestClient(app)
health = client.get("/health").json()
assert health == {"ok": True, "version": "0.3.29", "schema": 128}

uploaded = client.post(
    "/api/models/upload",
    files={"file": ("source-cube.stl", cube_stl(), "model/stl")},
    data={"title": "Source cube", "category": "Workshop"},
)
assert uploaded.status_code == 200, uploaded.text
source = uploaded.json()["model"]

# A design created from a library model preserves that source and starts in millimetres.
created = client.post("/api/workshop/designs", json={"name": "Bracket concept", "base_model_id": source["id"]})
assert created.status_code == 200, created.text
design = created.json()
assert design["revision"] == 1 and design["base_model_id"] == source["id"]
assert design["document"]["units"] == "mm" and len(design["document"]["objects"]) == 1
assert design["document"]["objects"][0]["model_id"] == source["id"]

# Primitive, hole, exact transforms and grid settings round-trip through the editable document.
document = design["document"]
document["grid"] = {"size_mm": 0.5, "snap": True, "visible": True}
document["objects"].extend([
    {"id": "solid-box", "kind": "box", "name": "Body", "operation": "solid", "color": "#67bea9",
     "visible": True, "locked": False, "position": [12.5, 5, -2], "rotation": [0, 0, 45],
     "scale": [1, 1, 1], "size": [20, 10, 8], "params": {"segments": 32}, "group_id": "mount-group"},
    {"id": "mounting-hole", "kind": "cylinder", "name": "Mounting hole", "operation": "hole", "color": "#ee7f63",
     "visible": True, "locked": False, "position": [12.5, 5, -2], "rotation": [90, 0, 0],
     "scale": [1, 1, 1], "size": [4, 14, 4], "params": {"segments": 48}, "group_id": "mount-group"},
])
saved = client.put(f"/api/workshop/designs/{design['id']}", json={"name": "Printable bracket", "revision": 1, "document": document})
assert saved.status_code == 200, saved.text
saved = saved.json()
assert saved["revision"] == 2 and saved["name"] == "Printable bracket"
assert saved["document"]["grid"]["size_mm"] == 0.5
assert saved["document"]["objects"][2]["operation"] == "hole"
assert {item["group_id"] for item in saved["document"]["objects"][1:]} == {"mount-group"}

# Optimistic revisions prevent an older tab from silently overwriting newer work.
stale = client.put(f"/api/workshop/designs/{design['id']}", json={"revision": 1, "document": document})
assert stale.status_code == 409
bad_revision = client.put(f"/api/workshop/designs/{design['id']}", json={"revision": "wrong", "document": document})
assert bad_revision.status_code == 422

# Malformed optional primitive parameters are safely normalised; missing library sources are rejected.
odd = client.post("/api/workshop/designs", json={"name": "Normalised", "document": {"objects": [
    {"id": "cone", "kind": "cone", "params": {"segments": "not-a-number", "top_radius_ratio": "bad"}}
]}})
assert odd.status_code == 200, odd.text
assert odd.json()["document"]["objects"][0]["params"] == {"segments": 32, "top_radius_ratio": 0.0}

# New dice and printable text are first-class editable objects, with text kept local and sanitised.
printable_shapes = client.post("/api/workshop/designs", json={"name": "Dice label", "document": {"objects": [
    {"id": "die", "kind": "d20", "name": "Blank D20", "size": [22, 22, 22]},
    {"id": "star", "kind": "star", "name": "Badge", "size": [26, 4, 26]},
    {"id": "tube", "kind": "ring", "name": "Spacer", "size": [20, 8, 20]},
    {"id": "label", "kind": "text", "name": "Player 1", "size": [42, 3, 12],
     "params": {"text": "Player 1 <script> / +", "font": "bold"}},
]}})
assert printable_shapes.status_code == 200, printable_shapes.text
printable_document = printable_shapes.json()["document"]
assert [item["kind"] for item in printable_document["objects"]] == ["d20", "star", "ring", "text"]
assert printable_document["objects"][0]["size"] == [22.0, 22.0, 22.0]
assert printable_document["objects"][3]["params"]["text"] == "PLAYER 1 SCRIPT /"
assert printable_document["objects"][3]["params"]["font"] == "bold"
assert len(printable_document["objects"][3]["params"]["text"]) <= 18
missing = client.post("/api/workshop/designs", json={"name": "Missing", "document": {"objects": [
    {"id": "missing", "kind": "model", "model_id": "does-not-exist"}
]}})
assert missing.status_code == 422

# The exact composed STL is stored as a child, immediately analysed, and leaves the source unchanged.
exported = client.post(
    f"/api/workshop/designs/{design['id']}/export",
    files={"file": ("printable-bracket.stl", cube_stl(12), "model/stl")},
    data={"title": "Printable bracket", "version_label": "Workshop export", "notes": "Solid/hole composition"},
)
assert exported.status_code == 200, exported.text
result = exported.json()
assert result["created"] is True
assert result["model"]["parent_model_id"] == source["id"]
assert result["model"]["derivation_type"] == "Remixed"
assert result["health"]["analyzable"] is True and result["health"]["metrics"]["watertight"] is True
reopened = client.get(f"/api/workshop/designs/{design['id']}").json()
assert reopened["last_export_model_id"] == result["model"]["id"]
assert client.get(f"/api/models/{source['id']}/health").json()["metrics"]["watertight"] is True

listed = client.get("/api/workshop/designs").json()
assert any(item["id"] == design["id"] and item["object_count"] == 3 for item in listed)
assert client.delete(f"/api/workshop/designs/{design['id']}").json() == {"ok": True}
assert client.get(f"/api/workshop/designs/{design['id']}").status_code == 404

print("LayerVault v0.3.29 Workshop CAD persistence, revision and health-gated export: PASS")
