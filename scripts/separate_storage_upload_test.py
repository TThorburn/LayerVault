import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
scratch = Path(tempfile.mkdtemp(prefix="layervault-cross-mount-upload-"))
workspace = scratch / "workspace"
models = scratch / "separate-model-store"
database = scratch / "separate-database"
os.environ.update({"DATA_DIR": str(workspace), "FILES_DIR": str(models), "DATABASE_DIR": str(database)})

from app.main import app  # noqa: E402


client = TestClient(app)
stl = b"""solid separate\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 10 0\nendloop\nendfacet\nendsolid separate\n"""
response = client.post(
    "/api/models/upload",
    files={"file": ("obj_2_single_color (12)_stl_A.stl", stl, "model/stl")},
    data={"category": "Parts"},
)
assert response.status_code == 200, response.text
model = response.json()["model"]
assert model["original_filename"] == "obj_2_single_color (12)_stl_A.stl"
assert (models / model["stored_filename"]).read_bytes() == stl
assert not any(workspace.glob("upload-*"))

print("LayerVault v0.3.29 separate-volume model upload regression: PASS")
