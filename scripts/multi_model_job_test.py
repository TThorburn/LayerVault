"""Multi-model print manifests, quantities, repeats and print counts."""
import os
import struct
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="layervault-multi-job-")

from app.main import app  # noqa: E402


def triangle_stl(name: str) -> bytes:
    header = name.encode("ascii")[:80].ljust(80, b"\0")
    triangle = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 10, 0, 0, 0, 10, 0, 0)
    return header + struct.pack("<I", 1) + triangle


client = TestClient(app)
assert client.get("/health").json() == {"ok": True, "version": "0.3.29", "schema": 128}
first = client.post("/api/models/upload", files={"file": ("captain.stl", triangle_stl("captain"), "model/stl")}).json()["model"]
second = client.post("/api/models/upload", files={"file": ("goblin.stl", triangle_stl("goblin"), "model/stl")}).json()["model"]

job = client.post("/api/jobs", json={
    "name": "Mixed plate", "status": "Complete",
    "models": [{"model_id": first["id"], "quantity": 2}, {"model_id": second["id"], "quantity": 4}],
}).json()
assert job["model_id"] == first["id"]
assert [(item["model_id"], item["quantity"]) for item in job["models"]] == [(first["id"], 2), (second["id"], 4)]
assert job["model_quantity"] == 6
models = {item["id"]: item for item in client.get("/api/models").json()}
assert models[first["id"]]["print_count"] == 2
assert models[second["id"]]["print_count"] == 4

repeat = client.post(f"/api/jobs/{job['id']}/repeat").json()
assert repeat["status"] == "Queued"
assert [(item["model_id"], item["quantity"]) for item in repeat["models"]] == [(first["id"], 2), (second["id"], 4)]

updated = client.patch(f"/api/jobs/{job['id']}", json={
    "models": [{"model_id": first["id"], "quantity": 1}], "status": "Complete",
}).json()
assert updated["models"][0]["quantity"] == 1 and len(updated["models"]) == 1
models = {item["id"]: item for item in client.get("/api/models").json()}
assert models[first["id"]]["print_count"] == 1
assert models[second["id"]]["print_count"] == 0

client.delete(f"/api/jobs/{job['id']}")
models = {item["id"]: item for item in client.get("/api/models").json()}
assert models[first["id"]]["print_count"] == 0

print("LayerVault v0.3.29 multi-model print manifest regression: PASS")
