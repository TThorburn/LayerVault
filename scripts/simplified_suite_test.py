import os
import sys
import tempfile
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="layervault-simplified-")

from app.main import app  # noqa: E402

assert app.version == "0.3.29"
compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
assert set(compose["services"]) == {"layervault", "sketchforge"}
assert set(compose["services"]["layervault"]["depends_on"]) == {"sketchforge"}
assert "GNU AFFERO GENERAL PUBLIC LICENSE" in (ROOT / "LICENSE").read_text(encoding="utf-8")
packager = (ROOT / "scripts/package_release.py").read_text(encoding="utf-8")
assert 'PREFIX = "layervault-suite"' in packager and '"LICENSE"' in packager

html = (ROOT / "app/templates/index.html").read_text(encoding="utf-8")
js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
css = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
for retired in ('data-page="fdm-slicer"', 'data-page="sla-slicer"', 'data-page="uvtools"'):
    assert retired not in html
assert "renderFdmSlicer" not in js
assert "renderSlaSlicer" not in js
assert "renderUvtools" not in js
assert "fdm-slicer-shell" not in css
assert "sla-slicer-shell" not in css
assert "uvtools-shell" not in css
assert "nebula" in html and "theme-preview-nebula" in css

client = TestClient(app)
licence = client.get("/license")
assert licence.status_code == 200 and b"GNU AFFERO GENERAL PUBLIC LICENSE" in licence.content

def check_owned_artwork(manufacturer: str, model: str, expected_provider: str) -> None:
    response = client.post("/api/printers", json={
        "name": model,
        "technology": "Resin" if expected_provider == "dragonfruit" else "FDM",
        "manufacturer": manufacturer,
        "model": model,
    })
    assert response.status_code == 200, response.text
    printer = response.json()
    assert printer["display_image_provider"] == expected_provider
    image = client.get(f'/api/printers/{printer["id"]}/image')
    assert image.status_code == 200, image.text
    assert image.headers["content-type"].startswith("image/")
    assert len(image.content) > 100

check_owned_artwork("Bambu Lab", "A1 mini", "orca")
check_owned_artwork("Creality", "K1C", "orca")
check_owned_artwork("Anycubic", "Photon M3", "dragonfruit")

print("LayerVault v0.3.29 simplified suite and printer artwork: PASS")
