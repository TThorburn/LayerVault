import os
import sys
import tempfile
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
os.environ.update({
    "DATA_DIR": str(data_dir),
    "DATABASE_DIR": str(database_dir),
    "FILES_DIR": str(models_dir),
    "BACKUP_DIR": str(backups_dir),
    "LAYERVAULT_DATA_PATH": "//PRINT-NAS/layervault/workspace",
    "LAYERVAULT_DATABASE_PATH": "C:/LayerVault/database",
    "LAYERVAULT_MODELS_PATH": "//PRINT-NAS/3d-models",
    "LAYERVAULT_BACKUPS_PATH": "//BACKUP-NAS/layervault",
})

from app.main import BACKUP_DIR, DATABASE_DIR, DB_PATH, FILES_DIR, app  # noqa: E402


client = TestClient(app)
assert client.get("/health").json() == {"ok": True, "version": "0.3.29", "schema": 128}
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

compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
service = compose["services"]["layervault"]
mounts = {item["target"]: item["source"] for item in service["volumes"]}
assert mounts["/data"] == "${LAYERVAULT_DATA_PATH:-./data}"
assert mounts["/storage/database"] == "${LAYERVAULT_DATABASE_PATH:-./data}"
assert mounts["/storage/models"] == "${LAYERVAULT_MODELS_PATH:-./data/files}"
assert mounts["/storage/backups"] == "${LAYERVAULT_BACKUPS_PATH:-./data/backups}"

js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
assert "function storageSettingsHtml" in js
assert "function downloadStorageEnvironment" in js
for theme in ("ocean", "orchid", "forest"):
    assert f"id:'{theme}'" in js
    assert f'data-theme="{theme}"' in css

print("LayerVault v0.3.29 external storage and expanded glass themes: PASS")
