"""Regression against real Anycubic PM3 and Bambu/Orca G-code 3MF exports."""
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="layervault-real-slicer-")

from app.main import app  # noqa: E402

pm3_path = Path(os.environ.get("LAYERVAULT_TEST_PM3", r"C:\Users\thoma\Downloads\test.pm3"))
three_mf_path = Path(os.environ.get("LAYERVAULT_TEST_GCODE_3MF", r"C:\Users\thoma\Downloads\test.gcode.3mf"))
assert pm3_path.is_file(), f"Missing PM3 fixture: {pm3_path}"
assert three_mf_path.is_file(), f"Missing G-code 3MF fixture: {three_mf_path}"

client = TestClient(app)
assert client.get("/health").json() == {"ok": True, "version": "0.3.29", "schema": 128}

resin_printer = client.post("/api/printers", json={
    "name": "Anycubic Photon M3", "manufacturer": "Anycubic", "model": "Photon M3",
    "technology": "MSLA / Resin", "printer_status": "Active",
}).json()
fdm_printer = client.post("/api/printers", json={
    "name": "Bambu Lab A1 mini", "manufacturer": "Bambu Lab", "model": "A1 mini",
    "technology": "FDM", "printer_status": "Active",
}).json()
resin_stock = client.post("/api/materials", json={
    "name": "JAYO Standard Resin Grey", "kind": "Resin", "material": "Standard Resin",
    "color": "Grey", "unit": "ml", "initial_amount": 1000, "remaining_amount": 1000,
}).json()
filament_stock = client.post("/api/materials", json={
    "name": "Bambu PLA Basic Black", "kind": "Filament", "material": "PLA", "brand": "Bambu Lab",
    "unit": "g", "initial_amount": 1000, "remaining_amount": 1000, "density_g_cm3": 1.26,
}).json()

with pm3_path.open("rb") as stream:
    resin_response = client.post("/api/jobs/toolpath/inspect", files={"file": (pm3_path.name, stream, "application/octet-stream")})
assert resin_response.status_code == 200, resin_response.text
resin = resin_response.json()
assert resin["technology"] == "Resin"
assert resin["printer_name"] == "Photon Mono M3"
assert resin["suggested_printer_id"] == resin_printer["id"]
assert resin["suggested_material_id"] == resin_stock["id"]
assert resin["duration_minutes"] == 158
assert abs(resin["material_volume_ml"] - 65.234) < 0.001
assert resin["settings"]["pixel_size_um"] == 40.0
assert resin["settings"]["bottom_exposure_s"] == 14.0
assert resin["settings"]["bottom_layers"] == 4
assert resin["settings"]["transition_layers"] == 10
assert resin["settings"]["lift_distance_mm"] == 6.0
assert resin["settings"]["lift_speed_mms"] == 1.5
assert resin["settings"]["retract_speed_mms"] == 3.3167
assert resin["settings"]["layer_height_mm"] == 0.05
assert resin["settings"]["normal_exposure_s"] == 2.75
assert resin["settings"]["light_off_delay_s"] == 0.5
assert not resin["warnings"]

with three_mf_path.open("rb") as stream:
    fdm_response = client.post("/api/jobs/toolpath/inspect", files={"file": (three_mf_path.name, stream, "application/octet-stream")})
assert fdm_response.status_code == 200, fdm_response.text
fdm = fdm_response.json()
assert fdm["technology"] == "FDM"
assert fdm["slicer"] == "Bambu Studio"
assert fdm["printer_name"] == "Bambu Lab A1 mini"
assert fdm["suggested_printer_id"] == fdm_printer["id"]
assert fdm["suggested_material_id"] == filament_stock["id"]
assert fdm["duration_minutes"] == 329
assert fdm["filament_length_mm"] == 17610.0
assert abs(fdm["material_weight_g"] - 53.38) < 0.001
assert abs(fdm["material_volume_ml"] - 42.357) < 0.001
assert fdm["settings"]["layer_height_mm"] == 0.12
assert fdm["settings"]["nozzle_temp_c"] == 220
assert fdm["settings"]["bed_temp_c"] == 60
assert fdm["settings"]["infill_percent"] == 10
assert fdm["settings"]["nozzle_mm"] == 0.4
assert not fdm["warnings"]

resin_job = client.post("/api/jobs", json={
    "name": "Real PM3 resin job", "printer_id": resin["suggested_printer_id"],
    "material_id": resin["suggested_material_id"], "technology": resin["technology"],
    "toolpath_token": resin["token"], "status": "Queued",
}).json()
assert resin_job["technology"] == "Resin"
assert resin_job["printer_id"] == resin_printer["id"]
assert resin_job["duration_minutes"] == 158
assert abs(resin_job["material_used"] - 65.234) < 0.001

fdm_job = client.post("/api/jobs", json={
    "name": "Real 3MF FDM job", "printer_id": fdm["suggested_printer_id"],
    "material_id": fdm["suggested_material_id"], "technology": fdm["technology"],
    "toolpath_token": fdm["token"], "status": "Queued",
}).json()
assert fdm_job["technology"] == "FDM"
assert fdm_job["printer_id"] == fdm_printer["id"]
assert fdm_job["duration_minutes"] == 329
assert abs(fdm_job["material_used"] - 53.38) < 0.001

print("LayerVault v0.3.29 real PM3 + G-code 3MF estimation and automatic setup regression: PASS")
