import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
data_dir = Path(tempfile.mkdtemp(prefix="layervault-backup-settings-"))
os.environ["DATA_DIR"] = str(data_dir)

from app.main import BACKUP_DIR, FILES_DIR, TOOLPATH_DIR, app  # noqa: E402

client = TestClient(app)
assert client.get("/health").json() == {"ok": True, "version": "0.3.29", "schema": 128}

(FILES_DIR / "sample-model.stl").write_bytes(b"solid sample\nendsolid sample\n")
(TOOLPATH_DIR / "sample-job.gcode").write_bytes(b"; sample print file\n")

initial = client.get("/api/settings/backups")
assert initial.status_code == 200
assert len(initial.json()["scopes"]) == 6
assert initial.json()["backups"] == []
assert initial.json()["schedules"] == []

scopes = ["database", "devices", "materials", "models", "projects", "print_logs"]
created = client.post("/api/settings/backups/run", json={"scopes": scopes})
assert created.status_code == 200, created.text
backup = created.json()
assert backup["scopes"] == scopes
archive_path = BACKUP_DIR / backup["file_name"]
assert archive_path.exists() and archive_path.suffix == ".zip"

with zipfile.ZipFile(archive_path) as archive:
    names = set(archive.namelist())
    assert "manifest.json" in names
    assert "database/layervault.db" in names
    assert "exports/devices/printers.json" in names
    assert "exports/materials/materials.json" in names
    assert "exports/models/models.json" in names
    assert "exports/projects/workshop_designs.json" in names
    assert "exports/print_logs/jobs.json" in names
    assert "files/models/sample-model.stl" in names
    assert "files/job-files/sample-job.gcode" in names
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["app_version"] == "0.3.29"
    assert manifest["schema_version"] == 128
    assert manifest["scopes"] == scopes

listing = client.get("/api/settings/backups").json()
assert listing["backups"][0]["id"] == backup["id"]
assert listing["storage_bytes"] == archive_path.stat().st_size
download = client.get(backup["download_url"])
assert download.status_code == 200 and download.content[:2] == b"PK"

schedule_response = client.post("/api/settings/backup-schedules", json={
    "name": "Nightly essentials",
    "frequency": "daily",
    "time_local": "03:15",
    "scopes": ["database", "models"],
    "keep_count": 7,
    "enabled": True,
})
assert schedule_response.status_code == 200, schedule_response.text
schedule = schedule_response.json()
assert schedule["name"] == "Nightly essentials"
assert schedule["frequency"] == "daily" and schedule["time_local"] == "03:15"
assert schedule["scopes"] == ["database", "models"]
assert schedule["keep_count"] == 7 and schedule["enabled"] is True
assert schedule["next_run_at"]

updated = client.patch(f"/api/settings/backup-schedules/{schedule['id']}", json={
    "frequency": "monthly", "month_day": 14, "enabled": False,
})
assert updated.status_code == 200
assert updated.json()["frequency"] == "monthly"
assert updated.json()["month_day"] == 14
assert updated.json()["enabled"] is False and updated.json()["next_run_at"] is None

assert client.delete(f"/api/settings/backup-schedules/{schedule['id']}").json() == {"ok": True}
assert client.delete(f"/api/settings/backups/{backup['id']}").json() == {"ok": True}
assert not archive_path.exists()
assert client.get("/api/settings/backups").json()["backups"] == []

print("LayerVault v0.3.29 scoped backup and schedule regression: PASS")
