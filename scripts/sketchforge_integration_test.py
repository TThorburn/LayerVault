import os
import sys
import tempfile
import zipfile
from pathlib import Path

import yaml
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
data_dir = Path(tempfile.mkdtemp(prefix="layervault-sketchforge-test-"))
os.environ["DATA_DIR"] = str(data_dir)

from app.main import SKETCHFORGE_PROJECTS_DIR, app  # noqa: E402


client = TestClient(app)
assert client.get("/health").json() == {"ok": True, "version": "0.3.29", "schema": 128}

html = client.get("/").text
assert '>Workshop</button>' in html
assert 'data-sketchforge-url=""' in html

js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
assert "if (state.page === 'workshop') return renderSketchForge();" in js
assert "async function renderSketchForge()" in js
assert "state.models = await api('/api/models');" in js
assert "function sketchForgeLibraryModal()" in js
assert "layervault:import-model" in js
assert "sketchforge:layervault-import-received" in js
assert "Formsmith746/SketchForge-3D" in js
assert "window.location.hostname}:3004" in js
assert ".sketchforge-frame-wrap iframe" in css
assert "no streamed desktop or VNC" in js

compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
services = compose["services"]
assert set(services) == {"layervault", "sketchforge"}
service = services["sketchforge"]
assert service["image"] == "layervault-sketchforge:local"
assert service["build"] == {
    "context": "./third_party/sketchforge",
    "dockerfile": "deploy/docker/Dockerfile",
}
assert "3004:3000" in service["ports"]
mounts = {item["target"]: item for item in service["volumes"]}
assert mounts["/data/projects"]["source"].endswith("/sketchforge/projects")
assert service["environment"]["SKETCHFORGE_SHARED_PROJECTS_DIR"] == "/data/projects"
assert services["layervault"]["depends_on"]["sketchforge"]["condition"] == "service_started"
assert all("container_name" not in item for item in services.values())

source = ROOT / "third_party/sketchforge"
for required in (
    "LICENSE",
    "README.md",
    "package.json",
    "package-lock.json",
    "apps/web/src/app/page.tsx",
    "deploy/docker/Dockerfile",
    "deploy/docker/start-server.mjs",
    "LAYERVAULT_INTEGRATION.md",
):
    assert (source / required).is_file(), required

package = (source / "package.json").read_text(encoding="utf-8")
page = (source / "apps/web/src/app/page.tsx").read_text(encoding="utf-8")
assert '"version": "1.0.7"' in package
assert '"license": "AGPL-3.0-only"' in package
assert 'message.type !== "layervault:import-model"' in page
assert "event.source !== window.parent || event.origin !== expectedOrigin" in page
assert "GNU AFFERO GENERAL PUBLIC LICENSE" in (source / "LICENSE").read_text(encoding="utf-8")
for generated in (".git", ".codex", ".codex-run", ".codex-remote-attachments", "node_modules", ".next", "apps/web/.next", "apps/web/out"):
    assert not (source / generated).exists(), generated

SKETCHFORGE_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
(SKETCHFORGE_PROJECTS_DIR / "integration-check.skf").write_bytes(b"SketchForge project")
backup = client.post("/api/settings/backups/run", json={"scopes": ["projects"]})
assert backup.status_code == 200, backup.text
archive = data_dir / "backups" / backup.json()["file_name"]
with zipfile.ZipFile(archive) as packaged:
    assert "files/sketchforge-projects/integration-check.skf" in packaged.namelist()

print("LayerVault v0.3.29 browser-native SketchForge Workshop integration: PASS")
