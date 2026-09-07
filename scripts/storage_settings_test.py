import os
import sys
import tempfile
import time
from pathlib import Path

import yaml
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
test_root = Path(tempfile.mkdtemp(prefix="layervault-storage-settings-"))
data_dir = test_root / "workspace"
database_dir = test_root / "database"
models_dir = test_root / "nas-models"
backups_dir = test_root / "offsite-backups"
mapped_root = test_root / "mapped-storage"
config_file = test_root / "config" / "storage.json"
os.environ.update({
    "DATA_DIR": str(data_dir),
    "DATABASE_DIR": str(database_dir),
    "FILES_DIR": str(models_dir),
    "BACKUP_DIR": str(backups_dir),
    "LAYERVAULT_DATA_PATH": "//PRINT-NAS/layervault/workspace",
    "LAYERVAULT_DATABASE_PATH": "C:/LayerVault/database",
    "LAYERVAULT_MODELS_PATH": "//PRINT-NAS/3d-models",
    "LAYERVAULT_BACKUPS_PATH": "//BACKUP-NAS/layervault",
    "STORAGE_CONFIG_FILE": str(config_file),
    "STORAGE_RESTART_ON_APPLY": "false",
    "STORAGE_ROOT_1_HOST": "/srv/portable-storage",
    "STORAGE_ROOT_1_CONTAINER": str(mapped_root),
})

from app.main import BACKUP_DIR, DATABASE_DIR, DB_PATH, FILES_DIR, app  # noqa: E402
import app.main as main_module  # noqa: E402


client = TestClient(app)
assert client.get("/health").json() == {"ok": True, "version": "0.3.33", "schema": 128}
assert DB_PATH == database_dir.resolve() / "layervault.db"
assert FILES_DIR == models_dir.resolve()
assert BACKUP_DIR == backups_dir.resolve()
assert all(path.is_dir() for path in (DATABASE_DIR, FILES_DIR, BACKUP_DIR))

settings = client.get("/api/settings/backups").json()
locations = settings["storage"]
assert locations["database"]["host_path"] == "C:/LayerVault/database"
assert locations["models"]["host_path"] == "//PRINT-NAS/3d-models"
assert locations["backups"]["host_path"] == "//BACKUP-NAS/layervault"
assert all(locations[key]["writable"] for key in ("workspace", "database", "models", "backups"))
assert locations["apply_enabled"] is True
assert locations["roots"][0]["host_path"] == "/srv/portable-storage"
assert locations["portainer_webhook_configured"] is False
assert client.post("/api/settings/storage/portainer-webhook", json={"url": "https://portainer.example/api/stacks/webhooks/test-token"}).status_code == 200
assert client.get("/api/settings/backups").json()["storage"]["portainer_webhook_configured"] is True
assert client.post("/api/settings/storage/portainer-webhook", json={"url": "file:///etc/passwd"}).status_code == 400
assert client.post("/api/settings/storage/portainer-webhook", json={"url": ""}).json()["configured"] is False

(data_dir / "workspace-marker.txt").write_text("workspace", encoding="utf-8")
(models_dir / "model-marker.stl").write_text("solid marker\nendsolid marker\n", encoding="utf-8")
move = client.post("/api/settings/storage/apply", json={
    "workspace": "/srv/portable-storage/LayerVault-Data",
    "database": "/srv/portable-storage/database",
    "models": "/srv/portable-storage/STLs",
    "backups": "/srv/portable-storage/backups",
})
assert move.status_code == 202, move.text
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    move_status = client.get("/api/settings/storage/apply/status").json()
    if move_status["state"] in {"complete", "failed"}:
        break
    time.sleep(0.05)
assert move_status["state"] == "complete", move_status
assert (mapped_root / "LayerVault-Data" / "workspace-marker.txt").is_file()
assert (mapped_root / "STLs" / "model-marker.stl").is_file()
assert (mapped_root / "database" / "layervault.db").is_file()
saved = __import__("json").loads(config_file.read_text(encoding="utf-8"))
assert saved["models"]["host_path"] == "/srv/portable-storage/STLs"
blocked = client.post("/api/settings/storage/apply", json={
    "workspace": "/etc/layervault", "database": "/etc/layervault", "models": "/etc/layervault", "backups": "/etc/layervault"
})
assert blocked.status_code == 400
client.post("/api/settings/storage/portainer-webhook", json={"url": "https://portainer.example/api/stacks/webhooks/test-token", "allow_insecure_tls": True})
webhook_calls = []
main_module._trigger_portainer_storage_remount = lambda paths: webhook_calls.append(paths)
remount = client.post("/api/settings/storage/apply", json={
    "workspace": "/new-host/LayerVault-Data",
    "database": "/new-host/database",
    "models": "/new-host/STLs",
    "backups": "/new-host/backups",
})
assert remount.status_code == 202 and remount.json()["state"] == "remounting", remount.text
deadline = time.monotonic() + 2
while time.monotonic() < deadline and not webhook_calls:
    time.sleep(0.01)
assert webhook_calls and webhook_calls[0]["models"] == "/new-host/STLs"
assert main_module.STORAGE_PENDING_FILE.is_file()
main_module.STORAGE_PENDING_FILE.unlink()

compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
service = compose["services"]["layervault"]
mounts = {item["target"]: item["source"] for item in service["volumes"]}
assert mounts["/data"] == "${LAYERVAULT_DATA_PATH:-./data}"
assert mounts["/storage/database"] == "${LAYERVAULT_DATABASE_PATH:-./data}"
assert mounts["/storage/models"] == "${LAYERVAULT_MODELS_PATH:-./data/files}"
assert mounts["/storage/backups"] == "${LAYERVAULT_BACKUPS_PATH:-./data/backups}"
assert mounts["/config"] == "layervault-storage-config"
assert mounts["/storage-roots/1"] == "${LAYERVAULT_STORAGE_ROOT_1:-./data}"

js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
assert "function storageSettingsHtml" in js
assert "function downloadStorageEnvironment" in js
assert "function applyStorageSettings" in js
assert "function saveStorageWebhook" in js
assert "Portainer one-click remount" in js
assert "Apply &amp; restart" in js
for theme in ("ocean", "orchid", "forest"):
    assert f"id:'{theme}'" in js
    assert f'data-theme="{theme}"' in css

print("LayerVault v0.3.33 safe portable storage apply and expanded glass themes: PASS")
