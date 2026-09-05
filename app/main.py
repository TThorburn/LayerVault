from __future__ import annotations

import hashlib
import io
import csv
import calendar
import json
import math
import os
import re
import queue
import secrets
import shutil
import sqlite3
import struct
import threading
import uuid
import zipfile
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps
from xml.etree import ElementTree as ET

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .catalog import configure as configure_catalog, providers as catalog_providers, search as catalog_search, detail as catalog_detail, image as catalog_image, image_from_official_page as catalog_official_image, official_artwork as catalog_official_artwork
from .printer_catalog import configure as configure_printer_catalog, providers as printer_catalog_providers, search as printer_catalog_search, detail as printer_catalog_detail, image as printer_catalog_image, remote_image as printer_remote_image, local_image_for_printer as printer_local_image
from .mesh_health import ENGINE_NAME as MESH_HEALTH_ENGINE, ENGINE_VERSION as MESH_HEALTH_VERSION, SUPPORTED as HEALTH_SUPPORTED, analyse_file as analyse_mesh_file, printer_fit as mesh_printer_fit, repair_file as repair_mesh_file, MANUFACTURING_ENGINE_VERSION, manufacturing_analysis_file, resin_prepare_file

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", APP_DIR.parent / "data")).resolve()
DATABASE_DIR = Path(os.getenv("DATABASE_DIR", DATA_DIR)).resolve()
FILES_DIR = Path(os.getenv("FILES_DIR", DATA_DIR / "files")).resolve()
IMPORT_DIR = DATA_DIR / "import"
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", DATA_DIR / "backups")).resolve()
THUMB_DIR = DATA_DIR / "thumbnails"
RESULT_DIR = DATA_DIR / "print-results"
TOOLPATH_DIR = DATA_DIR / "job-files"
TOOLPATH_UPLOAD_DIR = DATA_DIR / "toolpath-uploads"
CUSTOM_IMAGE_DIR = DATA_DIR / "custom-images"
CATALOG_CACHE_DIR = DATA_DIR / "catalog-cache"
SKETCHFORGE_PROJECTS_DIR = DATA_DIR / "sketchforge" / "projects"
SKETCHFORGE_URL = os.getenv("SKETCHFORGE_URL", "").strip()
DB_PATH = DATABASE_DIR / "layervault.db"
SUPPORTED = {".stl", ".obj", ".3mf", ".step", ".stp", ".gcode", ".bgcode", ".ctb", ".goo", ".lys", ".zip"}
PREVIEWABLE = {".stl", ".obj", ".3mf"}

for p in (DATA_DIR, DATABASE_DIR, FILES_DIR, IMPORT_DIR, BACKUP_DIR, THUMB_DIR, RESULT_DIR, TOOLPATH_DIR, TOOLPATH_UPLOAD_DIR, CUSTOM_IMAGE_DIR, CATALOG_CACHE_DIR, SKETCHFORGE_PROJECTS_DIR):
    p.mkdir(parents=True, exist_ok=True)
configure_catalog(DATA_DIR)
configure_printer_catalog(DATA_DIR)

app = FastAPI(title="LayerVault", version="0.3.29")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")

# The full application stylesheet is embedded into the HTML shell as a reliability
# fallback. LayerVault is a local app and the ~120 KB payload is small compared to
# model assets; embedding it prevents a proxy/browser/static-cache failure from
# ever degrading the UI to unstyled HTML. The source CSS file remains canonical.
STYLES_PATH = APP_DIR / "static" / "styles.css"
APP_JS_PATH = APP_DIR / "static" / "app.js"
LICENSE_PATH = APP_DIR.parent / "LICENSE"
INLINE_STYLES = STYLES_PATH.read_text(encoding="utf-8")
INLINE_APP_JS = (APP_DIR / "static" / "app.js").read_text(encoding="utf-8")

def _file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _asset_status() -> dict[str, dict]:
    assets = {
        "styles.css": STYLES_PATH,
        "app.js": APP_JS_PATH,
        "three.module.min.js": APP_DIR / "static" / "vendor" / "three.module.min.js",
        "OrbitControls.js": APP_DIR / "static" / "vendor" / "addons" / "controls" / "OrbitControls.js",
        "TransformControls.js": APP_DIR / "static" / "vendor" / "addons" / "controls" / "TransformControls.js",
        "BufferGeometryUtils.js": APP_DIR / "static" / "vendor" / "addons" / "utils" / "BufferGeometryUtils.js",
        "STLLoader.js": APP_DIR / "static" / "vendor" / "addons" / "loaders" / "STLLoader.js",
        "manifold.js": APP_DIR / "static" / "vendor" / "manifold" / "manifold.js",
        "manifold.wasm": APP_DIR / "static" / "vendor" / "manifold" / "manifold.wasm",
    }
    out = {}
    for name, path in assets.items():
        exists = path.exists() and path.is_file()
        out[name] = {
            "ok": exists,
            "bytes": path.stat().st_size if exists else 0,
            "sha256": _file_sha256(path) if exists else None,
        }
    return out
security = HTTPBasic(auto_error=False)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def auth(credentials: HTTPBasicCredentials | None = Depends(security)):
    expected_password = os.getenv("APP_PASSWORD", "")
    if not expected_password:
        return True
    expected_user = os.getenv("APP_USERNAME", "admin")
    good = credentials is not None and secrets.compare_digest(credentials.username, expected_user) and secrets.compare_digest(credentials.password, expected_password)
    if not good:
        raise HTTPException(status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Basic"})
    return True


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


CURRENT_SCHEMA_VERSION = 128


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Add additive alpha-era columns before indexes or queries can reference them.

    This is intentionally a small schema reconciler, not a permanent migration framework.
    It prevents an older test database from crash-looping the container while LayerVault
    is still in alpha. No existing columns or user rows are deleted.
    """
    existing = _table_columns(conn, table)
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')
            existing.add(name)


def _repair_inventory_codes(conn: sqlite3.Connection, table: str, prefix: str) -> None:
    """Ensure migrated physical inventory rows have non-empty, unique local codes."""
    rows = conn.execute(
        f'SELECT id, inventory_code FROM "{table}" ORDER BY COALESCE(created_at, ""), rowid'
    ).fetchall()
    used: set[str] = set()
    next_number = 1
    for row in rows:
        code = (row["inventory_code"] or "").strip()
        if not code or code in used:
            while f"{prefix}-{next_number:04d}" in used:
                next_number += 1
            code = f"{prefix}-{next_number:04d}"
            next_number += 1
            conn.execute(f'UPDATE "{table}" SET inventory_code=? WHERE id=?', (code, row["id"]))
        used.add(code)


def init_db():
    """Create/reconcile the current alpha schema safely before creating indexes.

    Alpha releases still do not promise full migration compatibility, but an older test
    database must never make the container crash simply because CREATE INDEX references
    a column introduced in a newer build. Tables are created first, known additive
    columns are reconciled, inventory identifiers are backfilled, then indexes are made.
    """
    table_schema = """
    CREATE TABLE IF NOT EXISTS models (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      original_filename TEXT NOT NULL,
      stored_filename TEXT NOT NULL,
      extension TEXT NOT NULL,
      size_bytes INTEGER NOT NULL DEFAULT 0,
      sha256 TEXT NOT NULL,
      category TEXT NOT NULL DEFAULT 'Unsorted',
      creator TEXT NOT NULL DEFAULT '',
      source_url TEXT NOT NULL DEFAULT '',
      license TEXT NOT NULL DEFAULT '',
      notes TEXT NOT NULL DEFAULT '',
      tags TEXT NOT NULL DEFAULT '[]',
      favorite INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'Ready',
      print_count INTEGER NOT NULL DEFAULT 0,
      triangles INTEGER,
      width_mm REAL,
      depth_mm REAL,
      height_mm REAL,
      added_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      parent_model_id TEXT,
      root_model_id TEXT,
      derivation_type TEXT NOT NULL DEFAULT 'Original',
      version_label TEXT NOT NULL DEFAULT 'Original',
      thumbnail_view TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS health_reports (
      model_id TEXT PRIMARY KEY REFERENCES models(id) ON DELETE CASCADE,
      sha256 TEXT NOT NULL,
      engine_version TEXT NOT NULL,
      score INTEGER NOT NULL DEFAULT 0,
      grade TEXT NOT NULL DEFAULT 'Unavailable',
      report_json TEXT NOT NULL DEFAULT '{}',
      analyzed_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS manufacturing_reports (
      model_id TEXT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
      printer_id TEXT NOT NULL REFERENCES printers(id) ON DELETE CASCADE,
      sha256 TEXT NOT NULL,
      engine_version TEXT NOT NULL,
      report_json TEXT NOT NULL DEFAULT '{}',
      analyzed_at TEXT NOT NULL,
      PRIMARY KEY(model_id, printer_id)
    );
    CREATE TABLE IF NOT EXISTS projects (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'Planning',
      tags TEXT NOT NULL DEFAULT '[]',
      due_date TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS project_models (
      project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      model_id TEXT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
      quantity INTEGER NOT NULL DEFAULT 1,
      variant TEXT NOT NULL DEFAULT '',
      urgency INTEGER NOT NULL DEFAULT 3,
      importance INTEGER NOT NULL DEFAULT 3,
      PRIMARY KEY(project_id, model_id)
    );
    CREATE TABLE IF NOT EXISTS workshop_designs (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      base_model_id TEXT REFERENCES models(id) ON DELETE SET NULL,
      last_export_model_id TEXT REFERENCES models(id) ON DELETE SET NULL,
      document_json TEXT NOT NULL DEFAULT '{}',
      revision INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS materials (
      id TEXT PRIMARY KEY,
      inventory_code TEXT NOT NULL,
      name TEXT NOT NULL,
      kind TEXT NOT NULL DEFAULT 'Filament',
      material TEXT NOT NULL DEFAULT 'PLA',
      brand TEXT NOT NULL DEFAULT '',
      color TEXT NOT NULL DEFAULT '',
      color_hex TEXT NOT NULL DEFAULT '#808080',
      density_g_cm3 REAL,
      diameter_mm REAL,
      gtin TEXT NOT NULL DEFAULT '',
      product_url TEXT NOT NULL DEFAULT '',
      initial_amount REAL NOT NULL DEFAULT 1000,
      remaining_amount REAL NOT NULL DEFAULT 1000,
      unit TEXT NOT NULL DEFAULT 'g',
      location TEXT NOT NULL DEFAULT '',
      supplier TEXT NOT NULL DEFAULT '',
      batch_lot TEXT NOT NULL DEFAULT '',
      purchase_price REAL,
      purchased_at TEXT,
      stock_status TEXT NOT NULL DEFAULT 'Open',
      notes TEXT NOT NULL DEFAULT '',
      opened_at TEXT,
      source_provider TEXT NOT NULL DEFAULT '',
      source_key TEXT NOT NULL DEFAULT '',
      source_url TEXT NOT NULL DEFAULT '',
      source_snapshot TEXT NOT NULL DEFAULT '{}',
      source_imported_at TEXT,
      source_image_url TEXT NOT NULL DEFAULT '',
      specs TEXT NOT NULL DEFAULT '{}',
      custom_image_asset_id TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS printers (
      id TEXT PRIMARY KEY,
      inventory_code TEXT NOT NULL,
      name TEXT NOT NULL,
      technology TEXT NOT NULL DEFAULT 'FDM',
      manufacturer TEXT NOT NULL DEFAULT '',
      model TEXT NOT NULL DEFAULT '',
      serial_number TEXT NOT NULL DEFAULT '',
      location TEXT NOT NULL DEFAULT '',
      purchased_at TEXT,
      purchase_price REAL,
      printer_status TEXT NOT NULL DEFAULT 'Active',
      firmware_version TEXT NOT NULL DEFAULT '',
      last_service_at TEXT,
      build_x REAL,
      build_y REAL,
      build_z REAL,
      nozzle_mm REAL,
      nozzle_options TEXT NOT NULL DEFAULT '[]',
      resolution_x INTEGER,
      resolution_y INTEGER,
      xy_resolution_x_um REAL,
      xy_resolution_y_um REAL,
      screen_width_mm REAL,
      screen_height_mm REAL,
      capabilities TEXT NOT NULL DEFAULT '{}',
      source_provider TEXT NOT NULL DEFAULT '',
      source_key TEXT NOT NULL DEFAULT '',
      source_url TEXT NOT NULL DEFAULT '',
      source_license TEXT NOT NULL DEFAULT '',
      source_snapshot TEXT NOT NULL DEFAULT '{}',
      source_imported_at TEXT,
      source_image_url TEXT NOT NULL DEFAULT '',
      custom_image_asset_id TEXT NOT NULL DEFAULT '',
      notes TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS custom_image_assets (
      id TEXT PRIMARY KEY,
      sha256 TEXT NOT NULL UNIQUE,
      filename TEXT NOT NULL,
      mime_type TEXT NOT NULL DEFAULT 'image/webp',
      width INTEGER,
      height INTEGER,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS custom_image_bindings (
      kind TEXT NOT NULL,
      identity_key TEXT NOT NULL,
      asset_id TEXT NOT NULL REFERENCES custom_image_assets(id) ON DELETE CASCADE,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(kind, identity_key)
    );
    CREATE TABLE IF NOT EXISTS profiles (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      technology TEXT NOT NULL DEFAULT 'FDM',
      printer_id TEXT REFERENCES printers(id) ON DELETE SET NULL,
      material TEXT NOT NULL DEFAULT '',
      layer_height REAL,
      settings TEXT NOT NULL DEFAULT '{}',
      notes TEXT NOT NULL DEFAULT '',
      profile_origin TEXT NOT NULL DEFAULT 'Local',
      source_provider TEXT NOT NULL DEFAULT '',
      source_key TEXT NOT NULL DEFAULT '',
      source_url TEXT NOT NULL DEFAULT '',
      source_snapshot TEXT NOT NULL DEFAULT '{}',
      source_imported_at TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS collections (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      kind TEXT NOT NULL DEFAULT 'manual',
      filter_json TEXT NOT NULL DEFAULT '{}',
      parent_id TEXT REFERENCES collections(id) ON DELETE SET NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS collection_models (
      collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
      model_id TEXT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
      added_at TEXT NOT NULL,
      PRIMARY KEY(collection_id, model_id)
    );
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
      model_id TEXT REFERENCES models(id) ON DELETE SET NULL,
      printer_id TEXT REFERENCES printers(id) ON DELETE SET NULL,
      material_id TEXT REFERENCES materials(id) ON DELETE SET NULL,
      profile_id TEXT REFERENCES profiles(id) ON DELETE SET NULL,
      technology TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'Queued',
      duration_minutes INTEGER,
      material_used REAL,
      material_cost REAL,
      settings_snapshot TEXT NOT NULL DEFAULT '{}',
      result_rating INTEGER,
      result_metrics TEXT NOT NULL DEFAULT '{}',
      result_photo TEXT NOT NULL DEFAULT '',
      toolpath_file TEXT NOT NULL DEFAULT '',
      toolpath_original_name TEXT NOT NULL DEFAULT '',
      toolpath_size_bytes INTEGER NOT NULL DEFAULT 0,
      toolpath_metadata TEXT NOT NULL DEFAULT '{}',
      failure_reason TEXT NOT NULL DEFAULT '',
      failure_tags TEXT NOT NULL DEFAULT '[]',
      counted_print INTEGER NOT NULL DEFAULT 0,
      counted_model_id TEXT,
      stock_deducted_amount REAL NOT NULL DEFAULT 0,
      stock_deducted_material_id TEXT,
      notes TEXT NOT NULL DEFAULT '',
      started_at TEXT,
      completed_at TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS job_models (
      job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
      model_id TEXT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
      quantity INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY(job_id, model_id)
    );
    CREATE TABLE IF NOT EXISTS material_transactions (
      id TEXT PRIMARY KEY,
      material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
      job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
      kind TEXT NOT NULL DEFAULT 'Adjustment',
      amount_delta REAL NOT NULL,
      balance_after REAL NOT NULL,
      note TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS backup_schedules (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      frequency TEXT NOT NULL DEFAULT 'weekly',
      time_local TEXT NOT NULL DEFAULT '02:00',
      weekday INTEGER NOT NULL DEFAULT 6,
      month_day INTEGER NOT NULL DEFAULT 1,
      scopes_json TEXT NOT NULL DEFAULT '[]',
      keep_count INTEGER NOT NULL DEFAULT 10,
      enabled INTEGER NOT NULL DEFAULT 1,
      last_run_at TEXT,
      next_run_at TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS backup_runs (
      id TEXT PRIMARY KEY,
      file_name TEXT NOT NULL UNIQUE,
      reason TEXT NOT NULL DEFAULT 'manual',
      schedule_id TEXT REFERENCES backup_schedules(id) ON DELETE SET NULL,
      scopes_json TEXT NOT NULL DEFAULT '[]',
      size_bytes INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL
    );
    """

    # Columns introduced after the first alpha schema. Definitions are deliberately
    # additive and use safe defaults so existing rows remain readable.
    additive_columns: dict[str, dict[str, str]] = {
        "models": {
            "parent_model_id": "TEXT",
            "root_model_id": "TEXT",
            "derivation_type": "TEXT NOT NULL DEFAULT 'Original'",
            "version_label": "TEXT NOT NULL DEFAULT 'Original'",
            "thumbnail_view": "TEXT NOT NULL DEFAULT '{}'",
        },
        "project_models": {
            "urgency": "INTEGER NOT NULL DEFAULT 3",
            "importance": "INTEGER NOT NULL DEFAULT 3",
        },
        "materials": {
            "inventory_code": "TEXT NOT NULL DEFAULT ''",
            "density_g_cm3": "REAL",
            "diameter_mm": "REAL",
            "gtin": "TEXT NOT NULL DEFAULT ''",
            "product_url": "TEXT NOT NULL DEFAULT ''",
            "supplier": "TEXT NOT NULL DEFAULT ''",
            "batch_lot": "TEXT NOT NULL DEFAULT ''",
            "purchase_price": "REAL",
            "purchased_at": "TEXT",
            "stock_status": "TEXT NOT NULL DEFAULT 'Open'",
            "source_provider": "TEXT NOT NULL DEFAULT ''",
            "source_key": "TEXT NOT NULL DEFAULT ''",
            "source_url": "TEXT NOT NULL DEFAULT ''",
            "source_snapshot": "TEXT NOT NULL DEFAULT '{}'",
            "source_imported_at": "TEXT",
            "source_image_url": "TEXT NOT NULL DEFAULT ''",
            "specs": "TEXT NOT NULL DEFAULT '{}'",
            "custom_image_asset_id": "TEXT NOT NULL DEFAULT ''",
        },
        "printers": {
            "inventory_code": "TEXT NOT NULL DEFAULT ''",
            "serial_number": "TEXT NOT NULL DEFAULT ''",
            "location": "TEXT NOT NULL DEFAULT ''",
            "purchased_at": "TEXT",
            "purchase_price": "REAL",
            "printer_status": "TEXT NOT NULL DEFAULT 'Active'",
            "firmware_version": "TEXT NOT NULL DEFAULT ''",
            "last_service_at": "TEXT",
            "nozzle_options": "TEXT NOT NULL DEFAULT '[]'",
            "resolution_x": "INTEGER",
            "resolution_y": "INTEGER",
            "xy_resolution_x_um": "REAL",
            "xy_resolution_y_um": "REAL",
            "screen_width_mm": "REAL",
            "screen_height_mm": "REAL",
            "capabilities": "TEXT NOT NULL DEFAULT '{}'",
            "source_provider": "TEXT NOT NULL DEFAULT ''",
            "source_key": "TEXT NOT NULL DEFAULT ''",
            "source_url": "TEXT NOT NULL DEFAULT ''",
            "source_license": "TEXT NOT NULL DEFAULT ''",
            "source_snapshot": "TEXT NOT NULL DEFAULT '{}'",
            "source_imported_at": "TEXT",
            "source_image_url": "TEXT NOT NULL DEFAULT ''",
            "custom_image_asset_id": "TEXT NOT NULL DEFAULT ''",
        },
        "profiles": {
            "profile_origin": "TEXT NOT NULL DEFAULT 'Local'",
            "source_provider": "TEXT NOT NULL DEFAULT ''",
            "source_key": "TEXT NOT NULL DEFAULT ''",
            "source_url": "TEXT NOT NULL DEFAULT ''",
            "source_snapshot": "TEXT NOT NULL DEFAULT '{}'",
            "source_imported_at": "TEXT",
        },
        "collections": {
            "parent_id": "TEXT",
        },
        "jobs": {
            "technology": "TEXT NOT NULL DEFAULT ''",
            "material_cost": "REAL",
            "settings_snapshot": "TEXT NOT NULL DEFAULT '{}'",
            "result_metrics": "TEXT NOT NULL DEFAULT '{}'",
            "result_photo": "TEXT NOT NULL DEFAULT ''",
            "toolpath_file": "TEXT NOT NULL DEFAULT ''",
            "toolpath_original_name": "TEXT NOT NULL DEFAULT ''",
            "toolpath_size_bytes": "INTEGER NOT NULL DEFAULT 0",
            "toolpath_metadata": "TEXT NOT NULL DEFAULT '{}'",
            "failure_reason": "TEXT NOT NULL DEFAULT ''",
            "failure_tags": "TEXT NOT NULL DEFAULT '[]'",
            "counted_print": "INTEGER NOT NULL DEFAULT 0",
            "counted_model_id": "TEXT",
            "counted_models_json": "TEXT NOT NULL DEFAULT '{}'",
            "stock_deducted_amount": "REAL NOT NULL DEFAULT 0",
            "stock_deducted_material_id": "TEXT",
        },
    }

    index_schema = """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_models_sha ON models(sha256);
    CREATE INDEX IF NOT EXISTS idx_models_added_at ON models(added_at DESC);
    CREATE INDEX IF NOT EXISTS idx_models_title ON models(title COLLATE NOCASE);
    CREATE INDEX IF NOT EXISTS idx_models_category ON models(category);
    CREATE INDEX IF NOT EXISTS idx_models_status ON models(status);
    CREATE INDEX IF NOT EXISTS idx_models_extension ON models(extension);
    CREATE INDEX IF NOT EXISTS idx_models_favorite ON models(favorite);
    CREATE INDEX IF NOT EXISTS idx_health_grade ON health_reports(grade, score DESC);
    CREATE INDEX IF NOT EXISTS idx_health_analyzed ON health_reports(analyzed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_manufacturing_analyzed ON manufacturing_reports(analyzed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_project_models_model ON project_models(model_id);
    CREATE INDEX IF NOT EXISTS idx_workshop_designs_updated ON workshop_designs(updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_workshop_designs_base ON workshop_designs(base_model_id);
    CREATE INDEX IF NOT EXISTS idx_collections_parent ON collections(parent_id);
    CREATE INDEX IF NOT EXISTS idx_collection_models_model ON collection_models(model_id);
    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
    CREATE INDEX IF NOT EXISTS idx_jobs_model ON jobs(model_id);
    CREATE INDEX IF NOT EXISTS idx_job_models_model ON job_models(model_id);
    CREATE INDEX IF NOT EXISTS idx_jobs_printer ON jobs(printer_id);
    CREATE INDEX IF NOT EXISTS idx_jobs_material ON jobs(material_id);
    CREATE INDEX IF NOT EXISTS idx_jobs_completed_at ON jobs(completed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_material_transactions_material ON material_transactions(material_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_material_transactions_job ON material_transactions(job_id);
    CREATE INDEX IF NOT EXISTS idx_jobs_recipe ON jobs(printer_id, material_id, model_id, status);
    CREATE INDEX IF NOT EXISTS idx_materials_source ON materials(source_provider, source_key);
    CREATE INDEX IF NOT EXISTS idx_profiles_source ON profiles(source_provider, source_key);
    CREATE INDEX IF NOT EXISTS idx_printers_source ON printers(source_provider, source_key);
    CREATE INDEX IF NOT EXISTS idx_custom_image_bindings_asset ON custom_image_bindings(asset_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_materials_inventory_code ON materials(inventory_code);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_printers_inventory_code ON printers(inventory_code);
    CREATE INDEX IF NOT EXISTS idx_backup_schedules_due ON backup_schedules(enabled, next_run_at);
    CREATE INDEX IF NOT EXISTS idx_backup_runs_created ON backup_runs(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_backup_runs_schedule ON backup_runs(schedule_id, created_at DESC);
    """

    with db() as conn:
        # Critical ordering: CREATE TABLE first, reconcile old tables second, INDEX last.
        conn.executescript(table_schema)
        for table, columns in additive_columns.items():
            _ensure_columns(conn, table, columns)

        _repair_inventory_codes(conn, "materials", "LV-MAT")
        _repair_inventory_codes(conn, "printers", "LV-PRN")
        # Reconcile existing stock with the expanded exact-match artwork index.
        # This also removes the few overly broad v0.3.23 matches rather than
        # leaving an unrelated bottle/model image attached to a product.
        legacy_artwork_pages = {
            "https://store.anycubic.com/products/colored-uv-resin",
            "https://www.elegoo.com/collections/standard-resins/products/elegoo-standard-resin-v-2-0",
            "https://www.sunlu.com/collections/2",
        }
        for material_row in conn.execute("SELECT id,brand,name,material,kind,color,source_image_url,specs,product_url FROM materials").fetchall():
            artwork = catalog_official_artwork(material_row["brand"], material_row["name"], material_row["material"], material_row["kind"], material_row["color"])
            if artwork:
                try:
                    existing_specs = json.loads(material_row["specs"] or "{}")
                    if not isinstance(existing_specs, dict): existing_specs = {}
                except (TypeError, json.JSONDecodeError):
                    existing_specs = {}
                merged_specs = {**artwork.get("specs", {}), **existing_specs}
                conn.execute("UPDATE materials SET source_image_url=?,specs=?,product_url=CASE WHEN product_url='' THEN ? ELSE product_url END WHERE id=?",
                             (artwork["url"], json.dumps(merged_specs, separators=(',',':')), artwork.get("product_url") or artwork["url"], material_row["id"]))
            elif material_row["source_image_url"] in legacy_artwork_pages:
                conn.execute("UPDATE materials SET source_image_url='' WHERE id=?", (material_row["id"],))
        # OpenPrintTag is no longer an active catalogue. Preserve already-imported
        # user inventory and recipes, but detach the retired source badge/key.
        conn.execute("UPDATE materials SET source_provider='',source_key='' WHERE source_provider='openprinttag'")
        conn.execute("UPDATE profiles SET source_provider='',source_key='' WHERE source_provider='openprinttag'")
        conn.execute("UPDATE models SET root_model_id=id WHERE root_model_id IS NULL OR root_model_id='' ")
        conn.execute("""INSERT OR IGNORE INTO job_models(job_id,model_id,quantity)
          SELECT id,model_id,1 FROM jobs WHERE model_id IS NOT NULL AND model_id<>''""")
        conn.executescript(index_schema)
        conn.execute(f"PRAGMA user_version={CURRENT_SCHEMA_VERSION}")


init_db()


def rowdict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for k in ("tags", "settings", "filter_json", "settings_snapshot", "result_metrics", "failure_tags", "thumbnail_view", "source_snapshot", "specs", "nozzle_options", "capabilities", "toolpath_metadata"):
        if k in d:
            try:
                d[k] = json.loads(d[k] or ("[]" if k in {"tags", "failure_tags"} else "{}"))
            except Exception:
                d[k] = [] if k in {"tags", "failure_tags"} else {}
    if "favorite" in d:
        d["favorite"] = bool(d["favorite"])
    return d


WORKSHOP_OBJECT_KINDS = {
    "model", "box", "cylinder", "sphere", "cone", "wedge", "pyramid", "hex", "star", "torus", "ring",
    "d4", "d6", "d8", "d10", "d12", "d20", "text",
}


def _workshop_vector(value: Any, default: list[float], *, positive: bool = False) -> list[float]:
    source = value if isinstance(value, list) and len(value) == 3 else default
    out: list[float] = []
    for index, fallback in enumerate(default):
        try:
            number = float(source[index])
            if not math.isfinite(number):
                number = fallback
        except (TypeError, ValueError, IndexError):
            number = fallback
        if positive:
            number = max(0.001, min(10000.0, abs(number)))
        else:
            number = max(-10000.0, min(10000.0, number))
        out.append(round(number, 6))
    return out


def _workshop_number(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
        if not math.isfinite(number):
            number = default
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def validate_workshop_document(value: Any, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HTTPException(422, "Workshop document must be a JSON object")
    raw_objects = value.get("objects")
    if not isinstance(raw_objects, list):
        raise HTTPException(422, "Workshop document requires an objects list")
    if len(raw_objects) > 150:
        raise HTTPException(422, "Workshop designs are limited to 150 objects in this release")
    objects = []
    seen: set[str] = set()
    model_ids: set[str] = set()
    for index, raw in enumerate(raw_objects):
        if not isinstance(raw, dict):
            raise HTTPException(422, f"Workshop object {index + 1} is invalid")
        object_id = str(raw.get("id") or "").strip()[:80]
        if not object_id or not re.fullmatch(r"[A-Za-z0-9_-]+", object_id) or object_id in seen:
            raise HTTPException(422, "Every Workshop object needs a unique id")
        seen.add(object_id)
        kind = str(raw.get("kind") or "").lower()
        if kind not in WORKSHOP_OBJECT_KINDS:
            raise HTTPException(422, f"Unsupported Workshop object type: {kind or 'empty'}")
        model_id = str(raw.get("model_id") or "").strip() if kind == "model" else ""
        if kind == "model":
            if not model_id:
                raise HTTPException(422, "Library model objects require model_id")
            model_ids.add(model_id)
        operation = str(raw.get("operation") or "solid").lower()
        if operation not in {"solid", "hole"}:
            operation = "solid"
        colour = str(raw.get("color") or ("#ee7f63" if operation == "hole" else "#67bea9"))
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
            colour = "#ee7f63" if operation == "hole" else "#67bea9"
        params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
        objects.append({
            "id": object_id,
            "kind": kind,
            "name": str(raw.get("name") or kind.title()).strip()[:120] or kind.title(),
            "model_id": model_id or None,
            "operation": operation,
            "color": colour.lower(),
            "visible": bool(raw.get("visible", True)),
            "locked": bool(raw.get("locked", False)),
            "group_id": str(raw.get("group_id") or "")[:80] or None,
            "position": _workshop_vector(raw.get("position"), [0.0, 10.0, 0.0]),
            "rotation": _workshop_vector(raw.get("rotation"), [0.0, 0.0, 0.0]),
            "scale": _workshop_vector(raw.get("scale"), [1.0, 1.0, 1.0], positive=True),
            "size": _workshop_vector(raw.get("size"), [20.0, 20.0, 20.0], positive=True),
            "params": {
                "segments": int(_workshop_number(params.get("segments"), 32.0, 8.0, 128.0)),
                "top_radius_ratio": _workshop_number(
                    params.get("top_radius_ratio"),
                    0.0 if kind == "cone" else 1.0,
                    0.0,
                    1.0,
                ),
                **({
                    "text": (
                        re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 .,!?:+\-_/]", "", str(params.get("text") or "TEXT").upper())).strip()[:18].strip()
                        or "TEXT"
                    ),
                    "font": str(params.get("font") or "classic").lower()
                    if str(params.get("font") or "classic").lower() in {"classic", "bold", "condensed"}
                    else "classic",
                } if kind == "text" else {}),
            },
        })
    if conn is not None and model_ids:
        placeholders = ",".join("?" for _ in model_ids)
        found = {row["id"] for row in conn.execute(f"SELECT id FROM models WHERE id IN ({placeholders})", tuple(model_ids)).fetchall()}
        missing = model_ids - found
        if missing:
            raise HTTPException(422, "A library model used by this Workshop design no longer exists")
    grid = value.get("grid") if isinstance(value.get("grid"), dict) else {}
    try:
        grid_size = max(0.1, min(25.0, float(grid.get("size_mm") or 1.0)))
    except (TypeError, ValueError):
        grid_size = 1.0
    return {
        "schema": 1,
        "units": "mm",
        "objects": objects,
        "grid": {"size_mm": round(grid_size, 3), "snap": bool(grid.get("snap", True)), "visible": bool(grid.get("visible", True))},
        "camera": value.get("camera") if isinstance(value.get("camera"), dict) else {},
    }


def workshop_design_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    try:
        document = json.loads(data.pop("document_json") or "{}")
    except Exception:
        document = {"schema": 1, "units": "mm", "objects": [], "grid": {"size_mm": 1.0, "snap": True, "visible": True}}
    data["document"] = document
    data["object_count"] = len(document.get("objects") or []) if isinstance(document, dict) else 0
    return data


def normalize_tags(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[,;]", value)
    seen, out = set(), []
    for item in raw:
        tag = str(item).strip()
        key = tag.casefold()
        if tag and key not in seen:
            seen.add(key)
            out.append(tag)
    return out[:50]



def as_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict): return value
    if isinstance(value, str):
        try:
            parsed=json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception: return {}
    return {}


def as_json_list(value: Any) -> list[Any]:
    if isinstance(value, list): return value
    if isinstance(value, str):
        try:
            parsed=json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception: return []
    return []


def next_inventory_code(conn: sqlite3.Connection, table: str, prefix: str) -> str:
    used=set()
    for row in conn.execute(f"SELECT inventory_code FROM {table} WHERE inventory_code LIKE ?", (f"{prefix}-%",)).fetchall():
        try: used.add(int(str(row[0]).rsplit('-',1)[-1]))
        except Exception: pass
    n=1
    while n in used: n += 1
    return f"{prefix}-{n:04d}"


def technology_family(value: str | None) -> str:
    v=(value or '').lower()
    return 'Resin' if any(x in v for x in ('resin','msla','sla','dlp')) else 'FDM'


def _identity_part(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")


def inventory_identity_keys(kind: str, row: sqlite3.Row | dict[str, Any]) -> list[str]:
    d = dict(row)
    keys: list[str] = []
    provider = _identity_part(d.get("source_provider"))
    source_key = str(d.get("source_key") or "").strip()
    if provider and source_key:
        keys.append(f"source:{provider}:{source_key}")
    if kind == "printer":
        manufacturer = _identity_part(d.get("manufacturer"))
        model = _identity_part(d.get("model"))
        if manufacturer or model:
            keys.append(f"machine:{manufacturer}:{model}")
        elif d.get("name"):
            keys.append(f"machine-name:{_identity_part(d.get('name'))}")
    else:
        gtin = _identity_part(d.get("gtin"))
        if gtin:
            keys.append(f"gtin:{gtin}")
        product = "material:" + ":".join(
            _identity_part(d.get(k)) for k in ("brand", "material", "color")
        )
        if product != "material:::":
            keys.append(product)
    # Preserve order while deduplicating aliases.
    return list(dict.fromkeys(k for k in keys if k))


def inventory_identity(kind: str, row: sqlite3.Row | dict[str, Any]) -> str:
    keys = inventory_identity_keys(kind, row)
    return keys[0] if keys else ""


def _bound_image_asset(conn: sqlite3.Connection, kind: str, row: sqlite3.Row | dict[str, Any]) -> str:
    for key in inventory_identity_keys(kind, row):
        found = conn.execute(
            "SELECT asset_id FROM custom_image_bindings WHERE kind=? AND identity_key=?",
            (kind, key),
        ).fetchone()
        if found:
            return found["asset_id"]
    return ""


def _apply_bound_image(conn: sqlite3.Connection, kind: str, table: str, item_id: str) -> None:
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (item_id,)).fetchone()
    if not row or row["custom_image_asset_id"]:
        return
    asset_id = _bound_image_asset(conn, kind, row)
    if asset_id:
        conn.execute(
            f"UPDATE {table} SET custom_image_asset_id=?, updated_at=? WHERE id=?",
            (asset_id, now_iso(), item_id),
        )
        _bind_current_item_image(conn, kind, table, item_id)


def _bind_current_item_image(conn: sqlite3.Connection, kind: str, table: str, item_id: str) -> None:
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (item_id,)).fetchone()
    if not row or not row["custom_image_asset_id"]:
        return
    for key in inventory_identity_keys(kind, row):
        conn.execute(
            """INSERT INTO custom_image_bindings(kind,identity_key,asset_id,updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(kind,identity_key) DO UPDATE SET asset_id=excluded.asset_id,updated_at=excluded.updated_at""",
            (kind, key, row["custom_image_asset_id"], now_iso()),
        )


def _store_custom_image(conn: sqlite3.Connection, payload: bytes) -> str:
    if not payload:
        raise HTTPException(400, "Image is empty")
    if len(payload) > 15 * 1024 * 1024:
        raise HTTPException(413, "Image is larger than 15 MB")
    try:
        image = Image.open(io.BytesIO(payload))
        image = ImageOps.exif_transpose(image)
        image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        buf = io.BytesIO()
        image.save(buf, format="WEBP", quality=90, method=6)
        webp = buf.getvalue()
        width, height = image.size
    except Exception as exc:
        raise HTTPException(400, f"Unsupported or invalid image: {exc}")
    sha = hashlib.sha256(webp).hexdigest()
    existing = conn.execute("SELECT id,filename FROM custom_image_assets WHERE sha256=?", (sha,)).fetchone()
    if existing:
        asset_id = existing["id"]
        filename = existing["filename"]
    else:
        asset_id = str(uuid.uuid4())
        filename = f"{sha}.webp"
        tmp = CUSTOM_IMAGE_DIR / f".{filename}.{uuid.uuid4().hex}.tmp"
        tmp.write_bytes(webp)
        tmp.replace(CUSTOM_IMAGE_DIR / filename)
        conn.execute(
            "INSERT INTO custom_image_assets(id,sha256,filename,mime_type,width,height,created_at) VALUES(?,?,?,?,?,?,?)",
            (asset_id, sha, filename, "image/webp", width, height, now_iso()),
        )
    path = CUSTOM_IMAGE_DIR / filename
    if not path.exists():
        path.write_bytes(webp)
    return asset_id


def _custom_image_response(conn: sqlite3.Connection, asset_id: str) -> FileResponse:
    row = conn.execute("SELECT filename,mime_type FROM custom_image_assets WHERE id=?", (asset_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Custom image not found")
    path = CUSTOM_IMAGE_DIR / row["filename"]
    if not path.exists():
        raise HTTPException(404, "Custom image file is missing")
    return FileResponse(path, media_type=row["mime_type"] or "image/webp", headers={"Cache-Control": "public, max-age=2592000"})


def material_with_metrics(conn: sqlite3.Connection, row: sqlite3.Row | None) -> dict[str, Any] | None:
    d=rowdict(row)
    if not d: return d
    initial=float(d.get('initial_amount') or 0); remaining=float(d.get('remaining_amount') or 0); price=d.get('purchase_price')
    d['remaining_percent']=round(max(0, remaining / initial * 100), 1) if initial > 0 else None
    d['low_stock']=bool(initial > 0 and remaining > 0 and remaining / initial <= .2)
    d['cost_per_unit']=round(float(price)/initial,6) if price is not None and initial > 0 else None
    d['remaining_value']=round(float(price)/initial*remaining,2) if price is not None and initial > 0 else None
    perf=conn.execute("""SELECT COUNT(*) attempts, SUM(CASE WHEN status='Complete' THEN 1 ELSE 0 END) successes,
      AVG(CASE WHEN result_rating IS NOT NULL THEN result_rating END) avg_rating, COALESCE(SUM(material_used),0) total_used
      FROM jobs WHERE material_id=? AND status IN ('Complete','Failed')""",(d['id'],)).fetchone()
    attempts=int(perf['attempts'] or 0); d['print_attempts']=attempts
    d['success_rate']=round(int(perf['successes'] or 0)/attempts*100,1) if attempts else None
    d['avg_rating']=round(float(perf['avg_rating']),2) if perf['avg_rating'] is not None else None
    d['total_used']=float(perf['total_used'] or 0)
    d['has_custom_image']=bool(d.get('custom_image_asset_id'))
    d['has_source_image']=bool(d.get('source_image_url'))
    return d


def printer_with_metrics(conn: sqlite3.Connection, row: sqlite3.Row | None) -> dict[str, Any] | None:
    d=rowdict(row)
    if not d: return d
    perf=conn.execute("""SELECT COUNT(*) attempts, SUM(CASE WHEN status='Complete' THEN 1 ELSE 0 END) successes,
      AVG(CASE WHEN result_rating IS NOT NULL THEN result_rating END) avg_rating, COALESCE(SUM(duration_minutes),0) minutes
      FROM jobs WHERE printer_id=? AND status IN ('Complete','Failed')""",(d['id'],)).fetchone()
    attempts=int(perf['attempts'] or 0); d['print_attempts']=attempts
    d['success_rate']=round(int(perf['successes'] or 0)/attempts*100,1) if attempts else None
    d['avg_rating']=round(float(perf['avg_rating']),2) if perf['avg_rating'] is not None else None
    d['print_hours']=round(float(perf['minutes'] or 0)/60,1)
    d['has_custom_image']=bool(d.get('custom_image_asset_id'))
    if not d.get('source_image_url'):
        artwork=printer_local_image(d.get('manufacturer',''),d.get('model') or d.get('name',''))
        if artwork:
            d['source_image_url']=artwork['image_url']; d['display_image_provider']=artwork['provider_id']; d['display_image_key']=artwork['key']
    return d


def add_material_transaction(conn: sqlite3.Connection, material_id: str, amount_delta: float, kind: str, note: str='', job_id: str|None=None):
    row=conn.execute("SELECT remaining_amount,stock_status FROM materials WHERE id=?",(material_id,)).fetchone()
    if not row: return
    balance=float(row['remaining_amount'] or 0)+float(amount_delta); status=row['stock_status'] or 'Open'
    if balance <= 0: status='Empty'
    elif status == 'Empty' or (kind.startswith('Print') and status == 'Sealed'): status='Open'
    conn.execute("UPDATE materials SET remaining_amount=?,stock_status=?,updated_at=? WHERE id=?",(balance,status,now_iso(),material_id))
    conn.execute("INSERT INTO material_transactions(id,material_id,job_id,kind,amount_delta,balance_after,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
                 (str(uuid.uuid4()),material_id,job_id,kind,float(amount_delta),balance,note,now_iso()))


def sync_job_model_count(conn: sqlite3.Connection, job_id: str):
    job=conn.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
    if not job: return
    old_counts={str(k):max(0,int(v or 0)) for k,v in as_json_dict(job['counted_models_json']).items() if k}
    if not old_counts and job['counted_model_id']:
        old_counts={str(job['counted_model_id']):1}
    desired_counts: dict[str,int]={}
    if job['status']=='Complete':
        linked=conn.execute("SELECT model_id,quantity FROM job_models WHERE job_id=?",(job_id,)).fetchall()
        desired_counts={str(row['model_id']):max(1,int(row['quantity'] or 1)) for row in linked}
        if not desired_counts and job['model_id']:
            desired_counts={str(job['model_id']):1}
    for model_id in set(old_counts)|set(desired_counts):
        delta=desired_counts.get(model_id,0)-old_counts.get(model_id,0)
        if delta:
            conn.execute("UPDATE models SET print_count=MAX(0,print_count+?),updated_at=? WHERE id=?",(delta,now_iso(),model_id))
    first_model=next(iter(desired_counts),None)
    conn.execute("UPDATE jobs SET counted_print=?,counted_model_id=?,counted_models_json=? WHERE id=?",(sum(desired_counts.values()),first_model,json.dumps(desired_counts,separators=(',',':')),job_id))


def replace_job_models(conn: sqlite3.Connection, job_id: str, raw_models: Any, fallback_model_id: str|None=None) -> list[dict[str,Any]]:
    """Persist a deduplicated model manifest and return it in display order."""
    entries=raw_models if isinstance(raw_models,list) else []
    combined: dict[str,int]={}
    order: list[str]=[]
    for entry in entries:
        if not isinstance(entry,dict): continue
        model_id=str(entry.get('model_id') or '').strip()
        if not model_id: continue
        quantity=max(1,min(999,int(entry.get('quantity') or 1)))
        if model_id not in combined: order.append(model_id)
        combined[model_id]=min(999,combined.get(model_id,0)+quantity)
    if not combined and fallback_model_id:
        combined[str(fallback_model_id)]=1;order=[str(fallback_model_id)]
    if combined:
        placeholders=','.join('?' for _ in combined)
        found={row['id'] for row in conn.execute(f"SELECT id FROM models WHERE id IN ({placeholders})",tuple(combined)).fetchall()}
        missing=set(combined)-found
        if missing: raise HTTPException(422,'One or more selected models no longer exist')
    conn.execute("DELETE FROM job_models WHERE job_id=?",(job_id,))
    for model_id in order:
        conn.execute("INSERT INTO job_models(job_id,model_id,quantity) VALUES(?,?,?)",(job_id,model_id,combined[model_id]))
    return [{'model_id':model_id,'quantity':combined[model_id]} for model_id in order]


def sync_job_stock(conn: sqlite3.Connection, job_id: str):
    job=conn.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
    if not job: return
    old_mid=job['stock_deducted_material_id']; old_amt=float(job['stock_deducted_amount'] or 0)
    finished=job['status'] in ('Complete','Failed')
    desired_mid=job['material_id'] if finished and job['material_id'] and float(job['material_used'] or 0)>0 else None
    desired_amt=float(job['material_used'] or 0) if desired_mid else 0.0
    if old_mid and old_amt and old_mid != desired_mid:
        add_material_transaction(conn,old_mid,old_amt,'Print stock correction','Restored after job material/status correction',job_id); old_mid=None; old_amt=0
    if desired_mid:
        if old_mid == desired_mid:
            delta=desired_amt-old_amt
            if abs(delta)>1e-9: add_material_transaction(conn,desired_mid,-delta,'Print stock correction','Adjusted to match updated material usage',job_id)
        else: add_material_transaction(conn,desired_mid,-desired_amt,'Print usage',f"Consumed by {job['name']}",job_id)
    elif old_mid and old_amt:
        add_material_transaction(conn,old_mid,old_amt,'Print stock correction','Restored because print is no longer complete/failed',job_id)
    material_cost=None
    if desired_mid and desired_amt:
        m=conn.execute("SELECT initial_amount,purchase_price FROM materials WHERE id=?",(desired_mid,)).fetchone()
        if m and m['purchase_price'] is not None and float(m['initial_amount'] or 0)>0:
            material_cost=round(float(m['purchase_price'])/float(m['initial_amount'])*desired_amt,4)
    conn.execute("UPDATE jobs SET stock_deducted_material_id=?,stock_deducted_amount=?,material_cost=? WHERE id=?",(desired_mid,desired_amt,material_cost,job_id))


def snapshot_settings(conn: sqlite3.Connection, profile_id: str|None, supplied: Any) -> dict[str, Any]:
    settings={}
    if profile_id:
        row=conn.execute("SELECT settings,layer_height FROM profiles WHERE id=?",(profile_id,)).fetchone()
        if row:
            try: settings.update(json.loads(row['settings'] or '{}'))
            except Exception: pass
            if row['layer_height'] is not None and 'layer_height_mm' not in settings: settings['layer_height_mm']=row['layer_height']
    settings.update(as_json_dict(supplied))
    return {k:v for k,v in settings.items() if v not in ('',None)}

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def bbox_from_points(points):
    if not points:
        return {}
    xs, ys, zs = zip(*points)
    return {
        "width_mm": round(max(xs) - min(xs), 3),
        "depth_mm": round(max(ys) - min(ys), 3),
        "height_mm": round(max(zs) - min(zs), 3),
    }


def inspect_stl(path: Path) -> dict[str, Any]:
    size = path.stat().st_size
    points = []
    triangles = None
    with path.open("rb") as f:
        head = f.read(84)
        if len(head) >= 84:
            count = struct.unpack("<I", head[80:84])[0]
            expected = 84 + count * 50
            if expected == size:
                triangles = count
                for _ in range(count):
                    chunk = f.read(50)
                    if len(chunk) < 50:
                        break
                    vals = struct.unpack("<12fH", chunk)
                    points.extend([(vals[3], vals[4], vals[5]), (vals[6], vals[7], vals[8]), (vals[9], vals[10], vals[11])])
                return {"triangles": triangles, **bbox_from_points(points)}
    text = path.read_text(errors="ignore")
    vertices = re.findall(r"\bvertex\s+([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)", text, flags=re.I)
    for x, y, z in vertices:
        try:
            points.append((float(x), float(y), float(z)))
        except ValueError:
            pass
    triangles = len(points) // 3 if points else None
    return {"triangles": triangles, **bbox_from_points(points)}


def inspect_obj(path: Path) -> dict[str, Any]:
    points, faces = [], 0
    with path.open("r", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        points.append(tuple(map(float, parts[1:4])))
                    except ValueError:
                        pass
            elif line.startswith("f "):
                faces += 1
    return {"triangles": faces if faces else None, **bbox_from_points(points)}


def inspect_3mf(path: Path) -> dict[str, Any]:
    points, triangles = [], 0
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".model")]
            for name in names:
                root = ET.fromstring(zf.read(name))
                for el in root.iter():
                    tag = el.tag.split("}")[-1]
                    if tag == "vertex":
                        try:
                            points.append((float(el.attrib["x"]), float(el.attrib["y"]), float(el.attrib["z"])))
                        except Exception:
                            pass
                    elif tag == "triangle":
                        triangles += 1
    except Exception:
        return {}
    return {"triangles": triangles or None, **bbox_from_points(points)}


def inspect_geometry(path: Path) -> dict[str, Any]:
    ext = path.suffix.lower()
    try:
        if ext == ".stl":
            return inspect_stl(path)
        if ext == ".obj":
            return inspect_obj(path)
        if ext == ".3mf":
            return inspect_3mf(path)
    except Exception:
        pass
    return {}


THUMB_RENDER_VERSION = "3"
THUMB_FULL_FACE_LIMIT = 700_000
THUMBNAIL_RENDER_LOCK = threading.Lock()
MESH_HEALTH_RENDER_LOCK = threading.Lock()
DEFAULT_THUMBNAIL_VIEW = {"yaw_deg": 22.0, "pitch_deg": 18.0, "zoom": 1.0}


def normalize_thumbnail_view(value: Any) -> dict[str, float]:
    """Return a bounded thumbnail camera definition.

    Yaw is measured around the model's Y/up axis with 0° looking from +Z.
    Pitch is the camera elevation above the model and zoom is relative to the
    automatic fit-to-frame scale.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except Exception:
            value = {}
    value = value if isinstance(value, dict) else {}
    try: yaw = float(value.get("yaw_deg", DEFAULT_THUMBNAIL_VIEW["yaw_deg"]))
    except Exception: yaw = DEFAULT_THUMBNAIL_VIEW["yaw_deg"]
    try: pitch = float(value.get("pitch_deg", DEFAULT_THUMBNAIL_VIEW["pitch_deg"]))
    except Exception: pitch = DEFAULT_THUMBNAIL_VIEW["pitch_deg"]
    try: zoom = float(value.get("zoom", DEFAULT_THUMBNAIL_VIEW["zoom"]))
    except Exception: zoom = DEFAULT_THUMBNAIL_VIEW["zoom"]
    yaw = ((yaw + 180.0) % 360.0) - 180.0
    pitch = max(-60.0, min(60.0, pitch))
    zoom = max(0.72, min(1.30, zoom))
    return {"yaw_deg": round(yaw, 3), "pitch_deg": round(pitch, 3), "zoom": round(zoom, 4)}


def effective_thumbnail_view(conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[dict[str, float], str | None, bool]:
    """Resolve the closest explicit camera in a lineage, otherwise use the default.

    An empty thumbnail_view means 'inherit'. This lets a root camera automatically
    flow to derived versions until a child receives its own override.
    """
    current = row
    seen: set[str] = set()
    while current and current["id"] not in seen:
        seen.add(current["id"])
        try:
            local = json.loads(current["thumbnail_view"] or "{}")
        except Exception:
            local = {}
        if isinstance(local, dict) and local:
            return normalize_thumbnail_view(local), current["id"], current["id"] != row["id"]
        parent_id = current["parent_model_id"]
        current = conn.execute("SELECT * FROM models WHERE id=?", (parent_id,)).fetchone() if parent_id else None
    return dict(DEFAULT_THUMBNAIL_VIEW), None, False


def _thumb_basis(view: dict[str, float]) -> tuple[tuple[float,float,float], tuple[float,float,float], tuple[float,float,float]]:
    """Camera basis matching a front-three-quarter, slightly elevated product view."""
    yaw = math.radians(view["yaw_deg"])
    pitch = math.radians(view["pitch_deg"])
    # Camera direction from model centre toward the camera.
    forward = (math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch))
    right = (math.cos(yaw), 0.0, -math.sin(yaw))
    up = (-math.sin(yaw) * math.sin(pitch), math.cos(pitch), -math.cos(yaw) * math.sin(pitch))
    return right, up, forward


def _thumb_project(x: float, y: float, z: float, view: dict[str, float]) -> tuple[float, float, float]:
    right, up, forward = _thumb_basis(view)
    return (
        x*right[0] + y*right[1] + z*right[2],
        x*up[0] + y*up[1] + z*up[2],
        x*forward[0] + y*forward[1] + z*forward[2],
    )


def _binary_stl_count(path: Path) -> int | None:
    """Return the triangle count only when the file is a valid binary STL."""
    try:
        size = path.stat().st_size
        if size < 84:
            return None
        with path.open("rb") as f:
            head = f.read(84)
        count = struct.unpack("<I", head[80:84])[0]
        return count if 84 + count * 50 == size else None
    except Exception:
        return None


def _expand_triangle(poly: list[tuple[float, float]], factor: float) -> list[tuple[float, float]]:
    if factor <= 1.01:
        return poly
    cx = sum(x for x, _ in poly) / 3.0
    cy = sum(y for _, y in poly) / 3.0
    return [(cx + (x - cx) * factor, cy + (y - cy) * factor) for x, y in poly]


def _fit_projected_bounds(min_x: float, max_x: float, min_y: float, max_y: float, size: tuple[int,int], zoom: float) -> tuple[float,float,float]:
    """Fit projected geometry tightly while reserving a little breathing room."""
    w, h = size
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    pad_x = w * 0.065
    pad_top = h * 0.055
    pad_bottom = h * 0.085
    scale = min((w - pad_x * 2) / span_x, (h - pad_top - pad_bottom) / span_y) * zoom
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    # Slight upward bias leaves a natural visual base below miniatures.
    target_y = pad_top + (h - pad_top - pad_bottom) * 0.48
    return scale, cx, cy - (target_y - h/2) / max(scale, 1e-9)


def _save_thumbnail_image(img: Image.Image, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    # Write atomically: the background pre-render worker and an on-demand browser request
    # can race, and clients must never observe a partially-written WebP.
    temp = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        img.save(temp, "WEBP", quality=88, method=6, exact=True)
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)


def _render_binary_stl_thumbnail(path: Path, output: Path, size: tuple[int, int], view: dict[str, float]) -> bool:
    """Render a dense binary STL to a cached WebP without topology-destroying decimation."""
    count = _binary_stl_count(path)
    if not count:
        return False

    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")
    try:
        with path.open("rb") as f:
            f.seek(84)
            for _ in range(count):
                chunk = f.read(50)
                if len(chunk) < 50:
                    return False
                vals = struct.unpack("<12fH", chunk)
                for x, y, z in ((vals[3], vals[4], vals[5]), (vals[6], vals[7], vals[8]), (vals[9], vals[10], vals[11])):
                    rx, ry, rz = _thumb_project(x, y, z, view)
                    min_x = min(min_x, rx); max_x = max(max_x, rx)
                    min_y = min(min_y, ry); max_y = max(max_y, ry)
                    min_z = min(min_z, rz); max_z = max(max_z, rz)
    except Exception:
        return False

    w, h = size
    scale, cx, cy = _fit_projected_bounds(min_x, max_x, min_y, max_y, size, view["zoom"])
    step = max(1, math.ceil(count / THUMB_FULL_FACE_LIMIT))
    expansion = 1.0 if step == 1 else min(3.0, max(1.12, math.sqrt(step) * 1.08))
    bucket_count = 96
    buckets = [bytearray() for _ in range(bucket_count)]
    record = struct.Struct("<7f")
    depth_span = max(max_z - min_z, 1e-9)
    # Bright studio light from above/front-left.
    light = (0.34, 0.68, 0.65)
    light_len = math.sqrt(sum(v*v for v in light)) or 1.0
    light = tuple(v/light_len for v in light)
    kept = 0

    try:
        with path.open("rb") as f:
            f.seek(84)
            for i in range(count):
                chunk = f.read(50)
                if len(chunk) < 50:
                    break
                if i % step:
                    continue
                vals = struct.unpack("<12fH", chunk)
                raw = ((vals[3], vals[4], vals[5]), (vals[6], vals[7], vals[8]), (vals[9], vals[10], vals[11]))
                tri = [_thumb_project(*v, view) for v in raw]
                p1,p2,p3 = raw
                ux,uy,uz = p2[0]-p1[0], p2[1]-p1[1], p2[2]-p1[2]
                vx,vy,vz = p3[0]-p1[0], p3[1]-p1[1], p3[2]-p1[2]
                nx,ny,nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
                ln = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
                diffuse = abs((nx*light[0] + ny*light[1] + nz*light[2]) / ln)
                shade = 0.62 + 0.38 * diffuse
                poly = _expand_triangle([((x-cx)*scale+w/2, h/2-(y-cy)*scale) for x,y,_ in tri], expansion)
                depth = sum(p[2] for p in tri) / 3.0
                bi = max(0, min(bucket_count - 1, int((depth - min_z) / depth_span * (bucket_count - 1))))
                buckets[bi] += record.pack(poly[0][0], poly[0][1], poly[1][0], poly[1][1], poly[2][0], poly[2][1], shade)
                kept += 1
    except Exception:
        return False

    if not kept:
        return False

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    draw.ellipse((w*.22, h*.80, w*.78, h*.91), fill=(32, 58, 74, 18))
    base = (104, 206, 183)
    for bucket in buckets:
        for x1,y1,x2,y2,x3,y3,shade in record.iter_unpack(bucket):
            fill = tuple(max(0, min(255, int(c * shade + 255 * (1.0 - shade) * 0.20))) for c in base) + (246,)
            draw.polygon(((x1,y1),(x2,y2),(x3,y3)), fill=fill)

    _save_thumbnail_image(img, output)
    return True


def thumbnail_mesh(path: Path, face_limit: int = 280_000):
    """Load a bounded mesh for non-binary-STL cached previews."""
    ext = path.suffix.lower()
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    try:
        if ext == ".stl":
            text = path.read_text(errors="ignore")
            tri = []
            for x,y,z in re.findall(r"\bvertex\s+([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)", text, flags=re.I):
                tri.append((float(x),float(y),float(z)))
                if len(tri) == 3:
                    base=len(verts); verts.extend(tri); faces.append((base,base+1,base+2)); tri=[]
                    if len(faces) >= face_limit: break
        elif ext == ".obj":
            with path.open("r", errors="ignore") as f:
                for line in f:
                    if line.startswith("v "):
                        parts=line.split()
                        if len(parts)>=4: verts.append(tuple(map(float,parts[1:4])))
                    elif line.startswith("f ") and len(faces) < face_limit:
                        idx=[]
                        for token in line.split()[1:]:
                            try:
                                n=int(token.split('/')[0]); idx.append(n-1 if n>0 else len(verts)+n)
                            except Exception: pass
                        for i in range(1,len(idx)-1):
                            if len(faces) >= face_limit: break
                            faces.append((idx[0],idx[i],idx[i+1]))
        elif ext == ".3mf":
            with zipfile.ZipFile(path) as zf:
                for name in [n for n in zf.namelist() if n.lower().endswith('.model')]:
                    root=ET.fromstring(zf.read(name)); local=[]
                    for el in root.iter():
                        tag=el.tag.split('}')[-1]
                        if tag=='vertex':
                            try: local.append((float(el.attrib['x']),float(el.attrib['y']),float(el.attrib['z'])))
                            except Exception: local.append((0,0,0))
                    base=len(verts); verts.extend(local)
                    for el in root.iter():
                        if el.tag.split('}')[-1]=='triangle' and len(faces)<face_limit:
                            try: faces.append((base+int(el.attrib['v1']),base+int(el.attrib['v2']),base+int(el.attrib['v3'])))
                            except Exception: pass
        return verts, faces
    except Exception:
        return [], []


def generate_thumbnail(path: Path, output: Path, size: tuple[int,int]=(640,460), view: dict[str,float] | None=None) -> bool:
    view = normalize_thumbnail_view(view or DEFAULT_THUMBNAIL_VIEW)
    if path.suffix.lower() == ".stl" and _binary_stl_count(path):
        return _render_binary_stl_thumbnail(path, output, size, view)

    verts, faces = thumbnail_mesh(path)
    if not verts or not faces:
        return False
    w,h=size
    transformed=[_thumb_project(x,y,z,view) for x,y,z in verts]
    xs=[v[0] for v in transformed]; ys=[v[1] for v in transformed]; zs=[v[2] for v in transformed]
    scale,cx,cy=_fit_projected_bounds(min(xs),max(xs),min(ys),max(ys),size,view["zoom"])
    pts=[((x-cx)*scale+w/2, h/2-(y-cy)*scale, z) for x,y,z in transformed]
    img=Image.new('RGBA',(w,h),(0,0,0,0)); draw=ImageDraw.Draw(img,'RGBA')
    draw.ellipse((w*.22,h*.80,w*.78,h*.91), fill=(32,58,74,18))
    light=(0.34,0.68,0.65); ll=math.sqrt(sum(v*v for v in light)) or 1; light=tuple(v/ll for v in light)
    painted=[]
    for a,b,c in faces:
        if max(a,b,c)>=len(pts): continue
        p1,p2,p3=verts[a],verts[b],verts[c]
        ux,uy,uz=p2[0]-p1[0],p2[1]-p1[1],p2[2]-p1[2]
        vx,vy,vz=p3[0]-p1[0],p3[1]-p1[1],p3[2]-p1[2]
        nx,ny,nz=uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
        ln=math.sqrt(nx*nx+ny*ny+nz*nz) or 1
        diffuse=abs((nx*light[0]+ny*light[1]+nz*light[2])/ln)
        shade=.62+.38*diffuse
        poly=[(pts[i][0],pts[i][1]) for i in (a,b,c)]
        painted.append(((pts[a][2]+pts[b][2]+pts[c][2])/3,poly,shade))
    painted.sort(key=lambda t:t[0])
    base=(104,206,183)
    for _,poly,shade in painted:
        fill=tuple(max(0,min(255,int(c*shade+255*(1.0-shade)*0.20))) for c in base)+(246,)
        draw.polygon(poly, fill=fill)
    _save_thumbnail_image(img, output)
    return True


def model_thumb_path(row) -> Path:
    return THUMB_DIR / f"{row['id']}-r{THUMB_RENDER_VERSION}.webp"


def invalidate_thumbnail_rows(rows: list[sqlite3.Row]) -> None:
    for row in rows:
        model_thumb_path(row).unlink(missing_ok=True)


def inheriting_thumbnail_rows(conn: sqlite3.Connection, model_id: str) -> list[sqlite3.Row]:
    """Current model plus descendants whose camera inherits through this branch."""
    root = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    if not root:
        return []
    out=[root]; pending=[model_id]
    while pending:
        pid=pending.pop()
        for child in conn.execute("SELECT * FROM models WHERE parent_model_id=?", (pid,)).fetchall():
            try: local=json.loads(child["thumbnail_view"] or "{}")
            except Exception: local={}
            if local:
                continue
            out.append(child); pending.append(child["id"])
    return out


THUMBNAIL_QUEUE: queue.Queue[str] = queue.Queue()
THUMBNAIL_PENDING: set[str] = set()
THUMBNAIL_PENDING_LOCK = threading.Lock()


def enqueue_thumbnail(model_id: str) -> bool:
    """Queue one preview without blocking upload/import requests."""
    with THUMBNAIL_PENDING_LOCK:
        if model_id in THUMBNAIL_PENDING:
            return False
        THUMBNAIL_PENDING.add(model_id)
    THUMBNAIL_QUEUE.put(model_id)
    return True


def _thumbnail_worker() -> None:
    while True:
        model_id = THUMBNAIL_QUEUE.get()
        try:
            with db() as conn:
                row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
                if not row or row["extension"] not in PREVIEWABLE:
                    continue
                view, _, _ = effective_thumbnail_view(conn, row)
            src = FILES_DIR / row["stored_filename"]
            out = model_thumb_path(row)
            if not src.exists():
                continue
            with THUMBNAIL_RENDER_LOCK:
                if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
                    generate_thumbnail(src, out, view=view)
        except Exception:
            # Preview generation must never make the library/import path fail.
            pass
        finally:
            with THUMBNAIL_PENDING_LOCK:
                THUMBNAIL_PENDING.discard(model_id)
            THUMBNAIL_QUEUE.task_done()


threading.Thread(target=_thumbnail_worker, name="layervault-thumbnail-worker", daemon=True).start()

def import_one_file(source: Path, metadata: dict[str, Any] | None = None, copy_source: bool = True) -> tuple[dict[str, Any], bool]:
    metadata = metadata or {}
    ext = source.suffix.lower()
    if ext not in SUPPORTED - {".zip"}:
        raise HTTPException(415, f"Unsupported file type: {ext}")
    digest = sha256_file(source)
    with db() as conn:
        existing = conn.execute("SELECT * FROM models WHERE sha256=?", (digest,)).fetchone()
        if existing:
            return rowdict(existing), False
    model_id = str(uuid.uuid4())
    stored_filename = f"{model_id}{ext}"
    target = FILES_DIR / stored_filename
    if copy_source:
        shutil.copy2(source, target)
    else:
        # DATA_DIR and FILES_DIR may deliberately be separate Docker/NAS
        # mounts. os.replace() fails with EXDEV across those filesystems;
        # shutil.move() retains the cheap rename on one disk and safely falls
        # back to copy+unlink when the model store is elsewhere.
        shutil.move(str(source), str(target))
    geom = inspect_geometry(target)
    original_filename = metadata.get("original_filename") or source.name
    title = (metadata.get("title") or Path(original_filename).stem).strip()
    timestamp = now_iso()
    values = (
        model_id, title, original_filename, stored_filename, ext, target.stat().st_size, digest,
        metadata.get("category") or "Unsorted", metadata.get("creator") or "", metadata.get("source_url") or "",
        metadata.get("license") or "", metadata.get("notes") or "", json.dumps(normalize_tags(metadata.get("tags"))),
        int(bool(metadata.get("favorite", False))), metadata.get("status") or "Ready", 0,
        geom.get("triangles"), geom.get("width_mm"), geom.get("depth_mm"), geom.get("height_mm"), timestamp, timestamp,
        metadata.get("parent_model_id") or None, metadata.get("root_model_id") or model_id,
        metadata.get("derivation_type") or "Original", metadata.get("version_label") or "Original",
        json.dumps(metadata.get("thumbnail_view") or {}),
    )
    with db() as conn:
        conn.execute("""INSERT INTO models
        (id,title,original_filename,stored_filename,extension,size_bytes,sha256,category,creator,source_url,license,notes,tags,favorite,status,print_count,triangles,width_mm,depth_mm,height_mm,added_at,updated_at,parent_model_id,root_model_id,derivation_type,version_label,thumbnail_view)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    if ext in PREVIEWABLE:
        enqueue_thumbnail(model_id)
    return rowdict(row), True


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(auth)])
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "app_version": app.version, "sketchforge_url": SKETCHFORGE_URL, "inline_styles": INLINE_STYLES, "inline_app_js": INLINE_APP_JS},
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


@app.get("/health")
def health():
    return {"ok": True, "version": app.version, "schema": CURRENT_SCHEMA_VERSION}


@app.get("/license", response_class=FileResponse, include_in_schema=False)
def licence_file():
    """Keep the LayerVault AGPL terms available to every local-network user."""
    if not LICENSE_PATH.is_file():
        raise HTTPException(404, "LayerVault licence file is not installed")
    return FileResponse(LICENSE_PATH, media_type="text/plain; charset=utf-8", filename="LayerVault-LICENSE.txt")


@app.get("/health/assets")
def health_assets():
    assets = _asset_status()
    core_ok = all(assets[name]["ok"] for name in ("styles.css", "app.js"))
    workshop_ok = all(assets[name]["ok"] for name in ("three.module.min.js", "OrbitControls.js", "TransformControls.js", "BufferGeometryUtils.js", "STLLoader.js", "manifold.js", "manifold.wasm"))
    return {
        "ok": core_ok,
        "version": app.version,
        "css_embedded": True,
        "js_embedded": True,
        "workshop_ok": workshop_ok,
        "css_bytes": len(INLINE_STYLES.encode("utf-8")),
        "js_bytes": len(INLINE_APP_JS.encode("utf-8")),
        "assets": assets,
    }


@app.get("/api/stats", dependencies=[Depends(auth)])
def stats():
    with db() as conn:
        models = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(size_bytes),0) b, COALESCE(SUM(print_count),0) p FROM models").fetchone()
        projects = conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"]
        materials = conn.execute("SELECT COUNT(*) c FROM materials").fetchone()["c"]
        printers = conn.execute("SELECT COUNT(*) c FROM printers").fetchone()["c"]
        low_stock = conn.execute("SELECT COUNT(*) c FROM materials WHERE initial_amount>0 AND remaining_amount>0 AND remaining_amount <= initial_amount*0.2").fetchone()["c"]
        jobs = conn.execute("SELECT status,COUNT(*) c FROM jobs GROUP BY status").fetchall()
        recent = conn.execute("SELECT * FROM models ORDER BY added_at DESC LIMIT 6").fetchall()
        cats = conn.execute("SELECT category,COUNT(*) c FROM models GROUP BY category ORDER BY c DESC LIMIT 8").fetchall()
    return {"models": models["c"], "bytes": models["b"], "prints": models["p"], "projects": projects, "materials": materials, "printers": printers, "low_stock": low_stock,
            "jobs": {r["status"]: r["c"] for r in jobs}, "recent": [rowdict(r) for r in recent], "categories": [dict(r) for r in cats]}


@app.get("/api/models", dependencies=[Depends(auth)])
def list_models(q: str = "", category: str = "", tag: str = "", extension: str = "", status: str = "", favorite: bool | None = None, sort: str = "newest", collection_id: str = "", unfiled: bool = False):
    where, args = [], []
    if collection_id:
        with db() as conn:
            c = conn.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
        if not c:
            raise HTTPException(404, "Collection not found")
        if c["kind"] == "manual":
            where.append("id IN (SELECT model_id FROM collection_models WHERE collection_id=?)"); args.append(collection_id)
        else:
            try: saved = json.loads(c["filter_json"] or "{}")
            except Exception: saved = {}
            q = q or saved.get("q", ""); category = category or saved.get("category", ""); tag = tag or saved.get("tag", "")
            extension = extension or saved.get("extension", ""); status = status or saved.get("status", "")
            if favorite is None and saved.get("favorite") is True: favorite = True
            if not unfiled and saved.get("unfiled") is True: unfiled = True
            if sort == "newest" and saved.get("sort"): sort = saved.get("sort")

    if unfiled:
        where.append("id NOT IN (SELECT model_id FROM collection_models)")
    if q:
        where.append("(title LIKE ? OR original_filename LIKE ? OR creator LIKE ? OR tags LIKE ? OR notes LIKE ?)")
        like = f"%{q}%"; args += [like] * 5
    if category:
        where.append("category=?"); args.append(category)
    if tag:
        where.append("tags LIKE ?"); args.append(f'%"{tag}"%')
    if extension:
        ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        where.append("extension=?"); args.append(ext)
    if status:
        where.append("status=?"); args.append(status)
    if favorite is not None:
        where.append("favorite=?"); args.append(int(favorite))
    order = {"newest": "added_at DESC", "oldest": "added_at ASC", "name": "title COLLATE NOCASE ASC", "prints": "print_count DESC", "size": "size_bytes DESC"}.get(sort, "added_at DESC")
    sql = "SELECT * FROM models" + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY {order}"
    with db() as conn:
        rows = conn.execute(sql, args).fetchall()
        health_rows = conn.execute("SELECT model_id,score,grade,analyzed_at FROM health_reports WHERE engine_version=?", (MESH_HEALTH_VERSION,)).fetchall()
    health_by_model = {r["model_id"]: dict(r) for r in health_rows}
    out = []
    for row in rows:
        item = rowdict(row)
        summary = health_by_model.get(item["id"])
        item["health"] = summary if summary else None
        out.append(item)
    return out


@app.post("/api/models/upload", dependencies=[Depends(auth)])
async def upload_model(file: UploadFile = File(...), title: str = Form(""), category: str = Form("Unsorted"), tags: str = Form(""), creator: str = Form(""), source_url: str = Form(""), license: str = Form(""), notes: str = Form("")):
    ext = Path(file.filename or "upload").suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(415, f"Supported: {', '.join(sorted(SUPPORTED))}")
    temp = DATA_DIR / f"upload-{uuid.uuid4()}{ext}"
    try:
        with temp.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
        metadata = {"title": title, "original_filename": file.filename or f"upload{ext}", "category": category, "tags": tags, "creator": creator, "source_url": source_url, "license": license, "notes": notes}
        if ext == ".zip":
            imported = []
            with zipfile.ZipFile(temp) as zf:
                members = [m for m in zf.infolist() if not m.is_dir() and Path(m.filename).suffix.lower() in SUPPORTED - {".zip"}]
                for member in members[:500]:
                    safe_name = Path(member.filename).name
                    extracted = DATA_DIR / f"extract-{uuid.uuid4()}-{safe_name}"
                    with zf.open(member) as src, extracted.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    try:
                        item, created = import_one_file(extracted, {**metadata, "title": "", "original_filename": safe_name})
                        imported.append({"model": item, "created": created})
                    finally:
                        extracted.unlink(missing_ok=True)
            return {"zip": True, "items": imported}
        item, created = import_one_file(temp, metadata, copy_source=False)
        return {"model": item, "created": created}
    finally:
        temp.unlink(missing_ok=True)


@app.get("/api/workshop/designs", dependencies=[Depends(auth)])
def list_workshop_designs():
    with db() as conn:
        rows = conn.execute("""SELECT d.*,b.title base_model_title,e.title last_export_title
          FROM workshop_designs d
          LEFT JOIN models b ON b.id=d.base_model_id
          LEFT JOIN models e ON e.id=d.last_export_model_id
          ORDER BY d.updated_at DESC""").fetchall()
    return [workshop_design_dict(row) for row in rows]


@app.post("/api/workshop/designs", dependencies=[Depends(auth)])
async def create_workshop_design(request: Request):
    data = await request.json()
    name = str(data.get("name") or "Untitled design").strip()[:120] or "Untitled design"
    base_model_id = str(data.get("base_model_id") or "").strip() or None
    with db() as conn:
        base = conn.execute("SELECT * FROM models WHERE id=?", (base_model_id,)).fetchone() if base_model_id else None
        if base_model_id and not base:
            raise HTTPException(404, "Base model not found")
        if "document" in data:
            document = validate_workshop_document(data.get("document"), conn)
        else:
            objects = []
            if base:
                size = [float(base["width_mm"] or 20), float(base["depth_mm"] or 20), float(base["height_mm"] or 20)]
                objects.append({
                    "id": f"obj-{uuid.uuid4().hex[:12]}", "kind": "model", "name": base["title"], "model_id": base["id"],
                    "operation": "solid", "color": "#67bea9", "visible": True, "locked": False, "group_id": None,
                    "position": [0, round(size[1] / 2, 6), 0], "rotation": [0, 0, 0], "scale": [1, 1, 1], "size": size,
                    "params": {"segments": 32, "top_radius_ratio": 1.0},
                })
            document = validate_workshop_document({"schema": 1, "units": "mm", "objects": objects, "grid": {"size_mm": 1, "snap": True, "visible": True}}, conn)
        stamp = now_iso()
        design_id = str(uuid.uuid4())
        conn.execute("INSERT INTO workshop_designs(id,name,base_model_id,last_export_model_id,document_json,revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                     (design_id, name, base_model_id, None, json.dumps(document, separators=(",", ":")), 1, stamp, stamp))
        row = conn.execute("SELECT * FROM workshop_designs WHERE id=?", (design_id,)).fetchone()
    return workshop_design_dict(row)


@app.get("/api/workshop/designs/{design_id}", dependencies=[Depends(auth)])
def get_workshop_design(design_id: str):
    with db() as conn:
        row = conn.execute("""SELECT d.*,b.title base_model_title,e.title last_export_title
          FROM workshop_designs d LEFT JOIN models b ON b.id=d.base_model_id LEFT JOIN models e ON e.id=d.last_export_model_id
          WHERE d.id=?""", (design_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Workshop design not found")
    return workshop_design_dict(row)


@app.put("/api/workshop/designs/{design_id}", dependencies=[Depends(auth)])
async def save_workshop_design(design_id: str, request: Request):
    data = await request.json()
    with db() as conn:
        current = conn.execute("SELECT * FROM workshop_designs WHERE id=?", (design_id,)).fetchone()
        if not current:
            raise HTTPException(404, "Workshop design not found")
        expected = data.get("revision")
        if expected is not None:
            try:
                expected_revision = int(expected)
            except (TypeError, ValueError):
                raise HTTPException(422, "Workshop revision must be an integer")
            if expected_revision != int(current["revision"]):
                raise HTTPException(409, "This design changed elsewhere. Reopen it before saving again.")
        document = validate_workshop_document(data.get("document"), conn)
        payload = json.dumps(document, separators=(",", ":"))
        if len(payload.encode("utf-8")) > 2 * 1024 * 1024:
            raise HTTPException(413, "Workshop design document is larger than 2 MB")
        name = str(data.get("name") or current["name"]).strip()[:120] or current["name"]
        revision = int(current["revision"]) + 1
        conn.execute("UPDATE workshop_designs SET name=?,document_json=?,revision=?,updated_at=? WHERE id=?",
                     (name, payload, revision, now_iso(), design_id))
        row = conn.execute("SELECT * FROM workshop_designs WHERE id=?", (design_id,)).fetchone()
    return workshop_design_dict(row)


@app.delete("/api/workshop/designs/{design_id}", dependencies=[Depends(auth)])
def delete_workshop_design(design_id: str):
    with db() as conn:
        if conn.execute("DELETE FROM workshop_designs WHERE id=?", (design_id,)).rowcount == 0:
            raise HTTPException(404, "Workshop design not found")
    return {"ok": True}


@app.post("/api/workshop/designs/{design_id}/export", dependencies=[Depends(auth)])
async def export_workshop_design(
    design_id: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    version_label: str = Form("Workshop Export"),
    notes: str = Form(""),
):
    with db() as conn:
        design = conn.execute("SELECT * FROM workshop_designs WHERE id=?", (design_id,)).fetchone()
        if not design:
            raise HTTPException(404, "Workshop design not found")
        stored_document = validate_workshop_document(json.loads(design["document_json"] or "{}"), conn)
        parent_id = design["base_model_id"] or next((obj.get("model_id") for obj in stored_document["objects"] if obj.get("model_id")), None)
        parent = conn.execute("SELECT * FROM models WHERE id=?", (parent_id,)).fetchone() if parent_id else None
    ext = Path(file.filename or "workshop-export.stl").suffix.lower()
    if ext != ".stl":
        raise HTTPException(415, "Workshop currently exports STL files")
    temp = DATA_DIR / f"workshop-export-{uuid.uuid4()}.stl"
    try:
        total = 0
        with temp.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > 200 * 1024 * 1024:
                    raise HTTPException(413, "Workshop export is larger than 200 MB")
                out.write(chunk)
        label = str(version_label or "Workshop Export").strip()[:80] or "Workshop Export"
        export_title = str(title or f"{design['name']} — {label}").strip()[:180]
        metadata = {
            "title": export_title,
            "original_filename": file.filename or "workshop-export.stl",
            "category": parent["category"] if parent else "Workshop",
            "creator": parent["creator"] if parent else "",
            "source_url": parent["source_url"] if parent else "",
            "license": parent["license"] if parent else "",
            "notes": notes or f"Editable Workshop design: {design['name']}",
            "tags": json.loads(parent["tags"] or "[]") if parent else ["Workshop"],
            "status": "Ready",
            "parent_model_id": parent["id"] if parent else None,
            "root_model_id": (parent["root_model_id"] or parent["id"]) if parent else None,
            "derivation_type": "Remixed",
            "version_label": label,
        }
        item, created = import_one_file(temp, metadata, copy_source=False)
        health_report, _ = _model_health_report(item["id"], refresh=True)
        with db() as conn:
            conn.execute("UPDATE workshop_designs SET last_export_model_id=?,updated_at=? WHERE id=?", (item["id"], now_iso(), design_id))
        return {"created": created, "model": item, "health": health_report, "design_id": design_id}
    finally:
        temp.unlink(missing_ok=True)


@app.get("/api/models/{model_id}/thumbnail", dependencies=[Depends(auth)])
def model_thumbnail(model_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Model not found")
        view, _, _ = effective_thumbnail_view(conn, row)
    if row["extension"] not in PREVIEWABLE: raise HTTPException(404, "Thumbnail unavailable")
    src = FILES_DIR / row["stored_filename"]
    if not src.exists(): raise HTTPException(410, "Stored file is missing")
    out = model_thumb_path(row)
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        # High-poly previews are rendered once to a compact WebP and then served like a
        # normal image. Serialising cold renders prevents a large library from spiking RAM.
        with THUMBNAIL_RENDER_LOCK:
            if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
                if not generate_thumbnail(src, out, view=view):
                    raise HTTPException(422, "Could not render thumbnail")
    return FileResponse(out, media_type="image/webp", headers={"Cache-Control":"public, max-age=31536000, immutable"})


@app.get("/api/models/{model_id}/thumbnail-view", dependencies=[Depends(auth)])
def get_thumbnail_view(model_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Model not found")
        effective, source_id, inherited = effective_thumbnail_view(conn, row)
        try: local = json.loads(row["thumbnail_view"] or "{}")
        except Exception: local = {}
    return {"local": local, "effective": effective, "source_id": source_id, "inherited": inherited, "default": dict(DEFAULT_THUMBNAIL_VIEW)}


@app.put("/api/models/{model_id}/thumbnail-view", dependencies=[Depends(auth)])
async def set_thumbnail_view(model_id: str, request: Request):
    data = normalize_thumbnail_view(await request.json())
    with db() as conn:
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Model not found")
        stamp=now_iso()
        conn.execute("UPDATE models SET thumbnail_view=?,updated_at=? WHERE id=?", (json.dumps(data), stamp, model_id))
        affected = inheriting_thumbnail_rows(conn, model_id)
        for inherited_row in affected[1:]:
            conn.execute("UPDATE models SET updated_at=? WHERE id=?", (stamp, inherited_row["id"]))
    invalidate_thumbnail_rows(affected)
    for affected_row in affected:
        enqueue_thumbnail(affected_row["id"])
    return get_thumbnail_view(model_id)


@app.delete("/api/models/{model_id}/thumbnail-view", dependencies=[Depends(auth)])
def reset_thumbnail_view(model_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Model not found")
        stamp=now_iso()
        conn.execute("UPDATE models SET thumbnail_view='{}',updated_at=? WHERE id=?", (stamp, model_id))
        affected = inheriting_thumbnail_rows(conn, model_id)
        for inherited_row in affected[1:]:
            conn.execute("UPDATE models SET updated_at=? WHERE id=?", (stamp, inherited_row["id"]))
    invalidate_thumbnail_rows(affected)
    for affected_row in affected:
        enqueue_thumbnail(affected_row["id"])
    return get_thumbnail_view(model_id)


@app.post("/api/models/bulk", dependencies=[Depends(auth)])
async def bulk_models(request: Request):
    d = await request.json(); ids = [str(x) for x in d.get("ids", []) if x]
    if not ids: raise HTTPException(400, "Choose at least one model")
    placeholders = ",".join("?" for _ in ids)
    action = d.get("action", "update")
    with db() as conn:
        rows = conn.execute(f"SELECT * FROM models WHERE id IN ({placeholders})", ids).fetchall()
        if action == "delete":
            files = [(r["stored_filename"], model_thumb_path(r)) for r in rows]
            conn.execute(f"DELETE FROM models WHERE id IN ({placeholders})", ids)
        else:
            updates = d.get("updates", {})
            allowed = {"category", "status", "favorite"}
            sets=[]; vals=[]
            for k in allowed:
                if k in updates:
                    sets.append(f"{k}=?"); vals.append(int(bool(updates[k])) if k=="favorite" else updates[k])
            if sets:
                sets.append("updated_at=?"); vals.append(now_iso()); conn.execute(f"UPDATE models SET {', '.join(sets)} WHERE id IN ({placeholders})", vals+ids)
            add_tags=normalize_tags(d.get("add_tags")); remove={x.casefold() for x in normalize_tags(d.get("remove_tags"))}
            if add_tags or remove:
                for r in rows:
                    tags=normalize_tags(json.loads(r["tags"] or "[]"))
                    tags=[t for t in tags if t.casefold() not in remove]
                    tags=normalize_tags(tags+add_tags)
                    conn.execute("UPDATE models SET tags=?,updated_at=? WHERE id=?", (json.dumps(tags),now_iso(),r["id"]))
            files=[]
    if action == "delete":
        for stored, thumb in files:
            (FILES_DIR/stored).unlink(missing_ok=True); thumb.unlink(missing_ok=True)
        return {"ok":True,"deleted":len(rows)}
    return {"ok":True,"updated":len(rows)}

def _model_health_report(model_id: str, refresh: bool = False) -> tuple[dict[str, Any], sqlite3.Row]:
    with db() as conn:
        model = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        if not model:
            raise HTTPException(404, "Model not found")
        cached = conn.execute("SELECT * FROM health_reports WHERE model_id=?", (model_id,)).fetchone()
    if model["extension"] not in HEALTH_SUPPORTED:
        report = {
            "analyzable": False, "engine": MESH_HEALTH_ENGINE, "engine_version": MESH_HEALTH_VERSION,
            "source_format": model["extension"].lstrip(".").upper(), "grade": "Unavailable", "score": 0,
            "summary": "Model Health currently analyses STL, OBJ and 3MF triangle meshes.", "metrics": {},
            "issues": [{"code":"unsupported","severity":"info","title":"Health analysis unavailable","detail":"This asset remains fully stored and catalogued, but this file type is not a triangle mesh that Pass 10 can inspect yet.","repairable":False}],
            "recommendations": [], "notes": []
        }
        return report, model
    if cached and not refresh and cached["sha256"] == model["sha256"] and cached["engine_version"] == MESH_HEALTH_VERSION:
        try:
            return json.loads(cached["report_json"]), model
        except Exception:
            pass
    path = FILES_DIR / model["stored_filename"]
    if not path.exists():
        raise HTTPException(410, "Stored file is missing")
    with MESH_HEALTH_RENDER_LOCK:
        report = analyse_mesh_file(path)
    stamp = now_iso(); report["analyzed_at"] = stamp
    with db() as conn:
        conn.execute("""INSERT INTO health_reports(model_id,sha256,engine_version,score,grade,report_json,analyzed_at)
          VALUES(?,?,?,?,?,?,?) ON CONFLICT(model_id) DO UPDATE SET sha256=excluded.sha256,engine_version=excluded.engine_version,
          score=excluded.score,grade=excluded.grade,report_json=excluded.report_json,analyzed_at=excluded.analyzed_at""",
          (model_id, model["sha256"], MESH_HEALTH_VERSION, int(report.get("score") or 0), report.get("grade") or "Unavailable", json.dumps(report), stamp))
    return report, model


def _manufacturing_report(model: sqlite3.Row, geometry_report: dict[str, Any], printer: dict[str, Any], refresh: bool = False) -> dict[str, Any]:
    printer_signature = hashlib.sha256(json.dumps({k: printer.get(k) for k in ("technology","build_x","build_y","build_z","nozzle_mm","resolution_x","resolution_y","xy_resolution_x_um","xy_resolution_y_um")}, sort_keys=True, default=str).encode()).hexdigest()[:16]
    with db() as conn:
        cached = conn.execute("SELECT * FROM manufacturing_reports WHERE model_id=? AND printer_id=?", (model["id"], printer["id"])).fetchone()
    if cached and not refresh and cached["sha256"] == model["sha256"] and cached["engine_version"] == MANUFACTURING_ENGINE_VERSION:
        try:
            cached_report = json.loads(cached["report_json"])
            if cached_report.get("printer_signature") == printer_signature:
                return cached_report
        except Exception:
            pass
    path = FILES_DIR / model["stored_filename"]
    if not path.exists():
        raise HTTPException(410, "Stored file is missing")
    with MESH_HEALTH_RENDER_LOCK:
        result = manufacturing_analysis_file(path, geometry_report, printer)
    stamp = now_iso(); result["analyzed_at"] = stamp; result["printer_signature"] = printer_signature
    with db() as conn:
        conn.execute("""INSERT INTO manufacturing_reports(model_id,printer_id,sha256,engine_version,report_json,analyzed_at)
          VALUES(?,?,?,?,?,?) ON CONFLICT(model_id,printer_id) DO UPDATE SET sha256=excluded.sha256,engine_version=excluded.engine_version,
          report_json=excluded.report_json,analyzed_at=excluded.analyzed_at""",
          (model["id"], printer["id"], model["sha256"], MANUFACTURING_ENGINE_VERSION, json.dumps(result), stamp))
    return result


def _health_with_printer(report: dict[str, Any], model: sqlite3.Row, printer_id: str = "", refresh: bool = False) -> dict[str, Any]:
    out = dict(report)
    out["printer_fit"] = None
    out["printer"] = None
    out["manufacturing"] = None
    if printer_id:
        with db() as conn:
            printer = conn.execute("SELECT * FROM printers WHERE id=?", (printer_id,)).fetchone()
        if not printer:
            raise HTTPException(404, "Printer not found")
        pd = rowdict(printer)
        out["printer"] = {k: pd.get(k) for k in ("id","name","technology","manufacturer","model","build_x","build_y","build_z","nozzle_mm","resolution_x","resolution_y","xy_resolution_x_um","xy_resolution_y_um")}
        out["printer_fit"] = mesh_printer_fit(report, pd)
        if report.get("analyzable"):
            out["manufacturing"] = _manufacturing_report(model, report, pd, refresh=refresh)
    return out


@app.get("/api/models/{model_id}/health", dependencies=[Depends(auth)])
def get_model_health(model_id: str, printer_id: str = "", refresh: bool = False):
    report, model = _model_health_report(model_id, refresh=refresh)
    return _health_with_printer(report, model, printer_id, refresh=refresh)


@app.post("/api/models/{model_id}/health/repair", dependencies=[Depends(auth)])
def repair_model_health(model_id: str):
    with db() as conn:
        parent = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    if not parent:
        raise HTTPException(404, "Model not found")
    if parent["extension"] not in HEALTH_SUPPORTED:
        raise HTTPException(415, "Safe Repair currently supports STL, OBJ and 3MF triangle meshes")
    source = FILES_DIR / parent["stored_filename"]
    if not source.exists():
        raise HTTPException(410, "Stored file is missing")
    temp = DATA_DIR / f"health-repair-{uuid.uuid4()}.stl"
    try:
        with MESH_HEALTH_RENDER_LOCK:
            result = repair_mesh_file(source, temp)
        if not result.get("changed"):
            return {"created": False, "message": result.get("validation_error") or "No conservative repair changes were needed.", "before": result.get("before"), "after": result.get("after"), "actions": []}
        notes = parent["notes"] or ""
        repair_note = "LayerVault Safe Repair: " + "; ".join(result.get("actions") or [])
        metadata = {
            "title": f"{parent['title']} — Safe Repair",
            "original_filename": f"{Path(parent['original_filename']).stem}-safe-repair.stl",
            "category": parent["category"], "creator": parent["creator"], "source_url": parent["source_url"], "license": parent["license"],
            "notes": (notes + ("\n\n" if notes else "") + repair_note).strip(), "tags": json.loads(parent["tags"] or "[]"),
            "status": "Ready" if result.get("after", {}).get("grade") == "Healthy" else "Needs repair",
            "parent_model_id": model_id, "root_model_id": parent["root_model_id"] or parent["id"],
            "derivation_type": "Repaired", "version_label": "Safe Repair",
        }
        item, created = import_one_file(temp, metadata, copy_source=False)
        # Re-open and analyse the library file. This verifies the exact persisted
        # artifact and also handles a repeated repair that reuses an existing child.
        persisted_after, _ = _model_health_report(item["id"], refresh=True)
        before_duplicates = int((result.get("before") or {}).get("metrics", {}).get("duplicate_faces") or 0)
        after_duplicates = int(persisted_after.get("metrics", {}).get("duplicate_faces") or 0)
        if before_duplicates and after_duplicates:
            raise HTTPException(500, f"Safe Repair could not verify duplicate removal ({after_duplicates:,} remain); the original was left unchanged.")
        return {
            "created": created, "reused": not created, "verified": True,
            "model": item, "source_model_id": model_id,
            "before": result.get("before"), "after": persisted_after,
            "actions": result.get("actions") or [],
            "message": "Existing verified repair opened." if not created else "Verified repair created.",
        }
    finally:
        temp.unlink(missing_ok=True)


@app.post("/api/models/{model_id}/manufacturing/repair", dependencies=[Depends(auth)])
async def repair_model_for_resin(model_id: str, request: Request):
    payload = await request.json()
    printer_id = str(payload.get("printer_id") or "")
    try:
        target_thickness = float(payload.get("target_thickness_mm") or 0.5)
    except (TypeError, ValueError):
        raise HTTPException(422, "Target thickness must be a number in millimetres")
    if not 0.3 <= target_thickness <= 2.0:
        raise HTTPException(422, "Target thickness must be between 0.30 and 2.00 mm")
    with db() as conn:
        parent = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        printer = conn.execute("SELECT * FROM printers WHERE id=?", (printer_id,)).fetchone() if printer_id else None
    if not parent:
        raise HTTPException(404, "Model not found")
    if not printer:
        raise HTTPException(422, "Select a resin printer before creating a Resin Preparation version")
    pd = rowdict(printer)
    technology = str(pd.get("technology") or "").lower()
    if not any(x in technology for x in ("resin", "sla", "msla", "dlp", "lcd")):
        raise HTTPException(422, "Resin Preparation requires a resin/SLA/MSLA/DLP printer profile")
    if parent["extension"] not in HEALTH_SUPPORTED:
        raise HTTPException(415, "Resin Preparation currently supports STL, OBJ and 3MF triangle meshes")
    source = FILES_DIR / parent["stored_filename"]
    if not source.exists():
        raise HTTPException(410, "Stored file is missing")
    geometry_before, _ = _model_health_report(model_id, refresh=True)
    manufacturing_before = _manufacturing_report(parent, geometry_before, pd, refresh=True)
    temp = DATA_DIR / f"resin-preparation-{uuid.uuid4()}.stl"
    try:
        with MESH_HEALTH_RENDER_LOCK:
            result = resin_prepare_file(source, temp, pd, target_thickness)
        if not result.get("changed"):
            return {"created": False, "message": result.get("validation_error") or "No substantial exposed thin feature or safely reducible suction change was found. The original was left unchanged.", "before": manufacturing_before, "after": manufacturing_before, "actions": []}
        with MESH_HEALTH_RENDER_LOCK:
            manufacturing_after = manufacturing_analysis_file(temp, result["after"], pd)
        preparation_limit = float(manufacturing_before.get("thickness", {}).get("caution_threshold_mm") or .35)
        before_thin = len([x for x in manufacturing_before.get("thickness", {}).get("broad_thin_regions", []) if float(x.get("estimated_p25_mm") or 999) < preparation_limit])
        after_thin = len([x for x in manufacturing_after.get("thickness", {}).get("broad_thin_regions", []) if float(x.get("estimated_p25_mm") or 999) < preparation_limit])
        before_suction = int(manufacturing_before.get("resin", {}).get("suction_pockets", {}).get("candidate_count") or 0)
        after_suction = int(manufacturing_after.get("resin", {}).get("suction_pockets", {}).get("candidate_count") or 0)
        before_islands = int(manufacturing_before.get("resin", {}).get("unsupported_minima", {}).get("candidate_count") or 0)
        after_islands = int(manufacturing_after.get("resin", {}).get("unsupported_minima", {}).get("candidate_count") or 0)
        regressions = []
        if int(manufacturing_after.get("score") or 0) < int(manufacturing_before.get("score") or 0): regressions.append("resin printability score decreased")
        if result.get("preparation", {}).get("thickness", {}).get("changed") and after_thin >= before_thin: regressions.append("exposed thin-feature count did not improve")
        if result.get("preparation", {}).get("orientation", {}).get("changed") and after_suction >= before_suction: regressions.append("suction candidate count did not improve")
        if after_islands > before_islands + 4: regressions.append("unsupported-island candidates increased materially")
        if regressions:
            return {"created": False, "message": "Resin Preparation rejected the candidate because " + ", ".join(regressions) + ". The original was left unchanged.", "before": manufacturing_before, "after": manufacturing_before, "actions": []}
        notes = parent["notes"] or ""
        action_note = "; ".join(result.get("actions") or [])
        repair_note = f"LayerVault Resin Preparation ({target_thickness:.2f} mm target): {action_note}. No automatic drain holes were added; confirm cups and islands in layer preview."
        label = f"Resin Prep {target_thickness:.2f} mm"
        metadata = {
            "title": f"{parent['title']} — {label}",
            "original_filename": f"{Path(parent['original_filename']).stem}-resin-prep-{target_thickness:.2f}mm.stl",
            "category": parent["category"], "creator": parent["creator"], "source_url": parent["source_url"], "license": parent["license"],
            "notes": (notes + ("\n\n" if notes else "") + repair_note).strip(), "tags": json.loads(parent["tags"] or "[]"),
            "status": "Ready" if int(manufacturing_after.get("score") or 0) >= 88 else "Needs supports",
            "parent_model_id": model_id, "root_model_id": parent["root_model_id"] or parent["id"],
            "derivation_type": "Repaired", "version_label": label,
        }
        item, created = import_one_file(temp, metadata, copy_source=False)
        persisted_geometry, _ = _model_health_report(item["id"], refresh=True)
        persisted_manufacturing = _manufacturing_report(item, persisted_geometry, pd, refresh=True)
        return {
            "created": created, "reused": not created, "verified": True, "model": item, "source_model_id": model_id,
            "target_thickness_mm": round(target_thickness, 3), "before": manufacturing_before, "after": persisted_manufacturing,
            "geometry_after": persisted_geometry, "actions": result.get("actions") or [], "preparation": result.get("preparation"),
            "improvements": {"broad_thin_regions": [before_thin, after_thin], "suction_candidates": [before_suction, after_suction], "island_candidates": [before_islands, after_islands]},
            "message": "Existing verified Resin Preparation opened." if not created else "Verified Resin Preparation created.",
        }
    finally:
        temp.unlink(missing_ok=True)


@app.get("/api/models/{model_id}", dependencies=[Depends(auth)])
def get_model(model_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    if not row: raise HTTPException(404, "Model not found")
    return rowdict(row)


@app.patch("/api/models/{model_id}", dependencies=[Depends(auth)])
async def update_model(model_id: str, request: Request):
    data = await request.json()
    allowed = {"title", "category", "creator", "source_url", "license", "notes", "status", "favorite", "print_count", "version_label", "derivation_type"}
    sets, args = [], []
    for key in allowed:
        if key in data:
            sets.append(f"{key}=?")
            args.append(int(data[key]) if key == "favorite" else data[key])
    if "tags" in data:
        sets.append("tags=?"); args.append(json.dumps(normalize_tags(data["tags"])))
    if not sets: return get_model(model_id)
    sets.append("updated_at=?"); args.append(now_iso()); args.append(model_id)
    with db() as conn:
        if conn.execute(f"UPDATE models SET {', '.join(sets)} WHERE id=?", args).rowcount == 0:
            raise HTTPException(404, "Model not found")
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    return rowdict(row)


@app.get("/api/models/{model_id}/lineage", dependencies=[Depends(auth)])
def model_lineage(model_id: str):
    with db() as conn:
        current = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        if not current:
            raise HTTPException(404, "Model not found")
        root_id = current["root_model_id"] or current["id"]
        family = conn.execute("SELECT * FROM models WHERE root_model_id=? OR id=? ORDER BY added_at ASC", (root_id, root_id)).fetchall()
        by_id = {r["id"]: rowdict(r) for r in family}
        if current["id"] not in by_id:
            by_id[current["id"]] = rowdict(current)
        children: dict[str, list[dict[str, Any]]] = {}
        for item in by_id.values():
            pid = item.get("parent_model_id")
            if pid:
                children.setdefault(pid, []).append(item)
        ancestors = []
        seen = set()
        cursor = by_id.get(current["parent_model_id"]) if current["parent_model_id"] else None
        while cursor and cursor["id"] not in seen:
            ancestors.insert(0, cursor); seen.add(cursor["id"]); cursor = by_id.get(cursor.get("parent_model_id"))
        return {"root_id": root_id, "current_id": model_id, "family": list(by_id.values()), "ancestors": ancestors, "children": children.get(model_id, [])}


@app.post("/api/models/{model_id}/derive", dependencies=[Depends(auth)])
async def derive_model(model_id: str, file: UploadFile = File(...), title: str = Form(""), version_label: str = Form("Derived"), derivation_type: str = Form("Modified"), notes: str = Form("")):
    with db() as conn:
        parent = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    if not parent:
        raise HTTPException(404, "Parent model not found")
    ext = Path(file.filename or "derived.stl").suffix.lower()
    if ext not in SUPPORTED - {".zip"}:
        raise HTTPException(415, "Unsupported derived file type")
    temp = DATA_DIR / f"derive-{uuid.uuid4()}{ext}"
    try:
        with temp.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
        metadata = {
            "title": title or f"{parent['title']} — {version_label or derivation_type}",
            "original_filename": file.filename or f"derived{ext}",
            "category": parent["category"], "creator": parent["creator"], "source_url": parent["source_url"],
            "license": parent["license"], "notes": notes or parent["notes"], "tags": json.loads(parent["tags"] or "[]"),
            "status": "Ready", "parent_model_id": model_id, "root_model_id": parent["root_model_id"] or parent["id"],
            "derivation_type": derivation_type or "Modified", "version_label": version_label or "Derived",
        }
        item, created = import_one_file(temp, metadata, copy_source=False)
        return {"model": item, "created": created}
    finally:
        temp.unlink(missing_ok=True)


@app.post("/api/models/{model_id}/lineage/link", dependencies=[Depends(auth)])
async def link_model_lineage(model_id: str, request: Request):
    data = await request.json(); parent_id = data.get("parent_model_id")
    if not parent_id or parent_id == model_id:
        raise HTTPException(400, "Choose a different parent model")
    with db() as conn:
        current = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        parent = conn.execute("SELECT * FROM models WHERE id=?", (parent_id,)).fetchone()
        if not current or not parent:
            raise HTTPException(404, "Model not found")
        # Prevent linking a root beneath one of its own descendants.
        cursor = parent
        seen = set()
        while cursor and cursor["id"] not in seen:
            if cursor["id"] == model_id:
                raise HTTPException(400, "That relationship would create a lineage cycle")
            seen.add(cursor["id"]); pid = cursor["parent_model_id"]
            cursor = conn.execute("SELECT * FROM models WHERE id=?", (pid,)).fetchone() if pid else None
        root_id = parent["root_model_id"] or parent["id"]
        conn.execute("UPDATE models SET parent_model_id=?,root_model_id=?,derivation_type=?,version_label=?,updated_at=? WHERE id=?",
                     (parent_id, root_id, data.get("derivation_type") or "Variant", data.get("version_label") or "Variant", now_iso(), model_id))
        # Re-root descendants too.
        pending=[model_id]
        while pending:
            pid=pending.pop()
            kids=conn.execute("SELECT id FROM models WHERE parent_model_id=?",(pid,)).fetchall()
            for kid in kids:
                conn.execute("UPDATE models SET root_model_id=? WHERE id=?",(root_id,kid["id"])); pending.append(kid["id"])
    return model_lineage(model_id)


@app.delete("/api/models/{model_id}", dependencies=[Depends(auth)])
def delete_model(model_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        if not row: raise HTTPException(404, "Model not found")
        child_count = conn.execute("SELECT COUNT(*) FROM models WHERE parent_model_id=?", (model_id,)).fetchone()[0]
        if child_count:
            raise HTTPException(409, f"This model has {child_count} derived version(s). Re-link or delete those first.")
        conn.execute("DELETE FROM models WHERE id=?", (model_id,))
    (FILES_DIR / row["stored_filename"]).unlink(missing_ok=True)
    model_thumb_path(row).unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/models/{model_id}/file", dependencies=[Depends(auth)])
def model_file(model_id: str, download: bool = False):
    with db() as conn:
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    if not row: raise HTTPException(404, "Model not found")
    path = FILES_DIR / row["stored_filename"]
    if not path.exists(): raise HTTPException(410, "Stored file is missing")
    media = "application/octet-stream"
    headers = {"Content-Disposition": f'{"attachment" if download else "inline"}; filename="{row["original_filename"]}"'}
    return FileResponse(path, media_type=media, filename=row["original_filename"] if download else None, headers=headers)


@app.post("/api/library/scan", dependencies=[Depends(auth)])
def scan_import_folder():
    results = {"created": 0, "duplicates": 0, "errors": [], "models": []}
    for path in sorted(IMPORT_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED - {".zip"}:
            continue
        try:
            model, created = import_one_file(path, {"category": path.parent.name if path.parent != IMPORT_DIR else "Imported"})
            results["models"].append(model)
            results["created" if created else "duplicates"] += 1
        except Exception as exc:
            results["errors"].append({"file": str(path.relative_to(IMPORT_DIR)), "error": str(exc)})
    return results


@app.get("/api/taxonomy", dependencies=[Depends(auth)])
def taxonomy():
    with db() as conn:
        categories = [r[0] for r in conn.execute("SELECT DISTINCT category FROM models WHERE category<>'' ORDER BY category COLLATE NOCASE")]
        rows = conn.execute("SELECT tags FROM models").fetchall()
    tags = sorted({t for r in rows for t in normalize_tags(json.loads(r[0] or "[]"))}, key=str.casefold)
    return {"categories": categories, "tags": tags}


@app.get("/api/collections", dependencies=[Depends(auth)])
def collections():
    with db() as conn:
        rows=conn.execute("SELECT * FROM collections ORDER BY name COLLATE NOCASE").fetchall()
        result=[]
        for r in rows:
            d=rowdict(r)
            if r["kind"]=="manual":
                d["model_count"]=conn.execute("SELECT COUNT(*) FROM collection_models WHERE collection_id=?",(r["id"],)).fetchone()[0]
            else:
                f=d.get("filter_json",{}) or {}; where=[]; args=[]
                if f.get("q"):
                    like=f"%{f['q']}%"; where.append("(title LIKE ? OR original_filename LIKE ? OR creator LIKE ? OR tags LIKE ? OR notes LIKE ?)"); args += [like]*5
                if f.get("category"): where.append("category=?"); args.append(f["category"])
                if f.get("tag"): where.append("tags LIKE ?"); args.append(f'%"{f["tag"]}"%')
                if f.get("extension"): where.append("extension=?"); args.append(f["extension"])
                if f.get("status"): where.append("status=?"); args.append(f["status"])
                if f.get("favorite"): where.append("favorite=1")
                if f.get("unfiled"): where.append("id NOT IN (SELECT model_id FROM collection_models)")
                d["model_count"]=conn.execute("SELECT COUNT(*) FROM models"+(" WHERE "+" AND ".join(where) if where else ""),args).fetchone()[0]
            d["child_count"]=conn.execute("SELECT COUNT(*) FROM collections WHERE parent_id=?",(r["id"],)).fetchone()[0]
            result.append(d)
    return result


def _validate_collection_parent(conn: sqlite3.Connection, collection_id: str | None, parent_id: str | None) -> None:
    if not parent_id:
        return
    parent=conn.execute("SELECT * FROM collections WHERE id=?",(parent_id,)).fetchone()
    if not parent:
        raise HTTPException(404,"Parent folder not found")
    if parent["kind"] != "manual":
        raise HTTPException(400,"Only normal folders can contain subfolders")
    if collection_id and parent_id == collection_id:
        raise HTTPException(400,"A folder cannot contain itself")
    # Walk upward from the proposed parent to prevent cycles.
    seen=set(); cursor=parent
    while cursor and cursor["id"] not in seen:
        if collection_id and cursor["id"] == collection_id:
            raise HTTPException(400,"That move would create a folder cycle")
        seen.add(cursor["id"])
        pid=cursor["parent_id"]
        cursor=conn.execute("SELECT * FROM collections WHERE id=?",(pid,)).fetchone() if pid else None


@app.post("/api/collections", dependencies=[Depends(auth)])
async def create_collection(request: Request):
    d=await request.json(); cid=str(uuid.uuid4()); ts=now_iso(); kind=d.get("kind","manual")
    if kind not in {"manual","smart"}: raise HTTPException(400,"Invalid collection kind")
    filt=d.get("filter",{}) if kind=="smart" else {}
    parent_id=d.get("parent_id") or None
    with db() as conn:
        _validate_collection_parent(conn,None,parent_id)
        conn.execute("INSERT INTO collections(id,name,description,kind,filter_json,parent_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(cid,d.get("name") or "Untitled folder",d.get("description", ""),kind,json.dumps(filt),parent_id,ts,ts))
        row=conn.execute("SELECT * FROM collections WHERE id=?",(cid,)).fetchone()
    return rowdict(row)


@app.get("/api/collections/{collection_id}", dependencies=[Depends(auth)])
def collection_detail(collection_id: str):
    with db() as conn:
        row=conn.execute("SELECT * FROM collections WHERE id=?",(collection_id,)).fetchone()
        if not row: raise HTTPException(404,"Collection not found")
        children=[rowdict(r) for r in conn.execute("SELECT * FROM collections WHERE parent_id=? ORDER BY name COLLATE NOCASE",(collection_id,)).fetchall()]
    d=rowdict(row)
    d["models"]=list_models(collection_id=collection_id)
    d["model_count"]=len(d["models"])
    d["children"]=children
    return d


@app.patch("/api/collections/{collection_id}", dependencies=[Depends(auth)])
async def update_collection(collection_id: str, request: Request):
    d=await request.json(); sets=[]; args=[]
    for k in ("name","description"):
        if k in d: sets.append(f"{k}=?"); args.append(d[k])
    if "filter" in d: sets.append("filter_json=?"); args.append(json.dumps(d["filter"]))
    with db() as conn:
        current=conn.execute("SELECT * FROM collections WHERE id=?",(collection_id,)).fetchone()
        if not current: raise HTTPException(404,"Collection not found")
        if "parent_id" in d:
            parent_id=d.get("parent_id") or None
            _validate_collection_parent(conn,collection_id,parent_id)
            sets.append("parent_id=?"); args.append(parent_id)
        if not sets:
            return collection_detail(collection_id)
        sets.append("updated_at=?"); args.append(now_iso()); args.append(collection_id)
        conn.execute(f"UPDATE collections SET {', '.join(sets)} WHERE id=?",args)
    return collection_detail(collection_id)


@app.delete("/api/collections/{collection_id}", dependencies=[Depends(auth)])
def delete_collection(collection_id: str):
    with db() as conn: conn.execute("DELETE FROM collections WHERE id=?",(collection_id,))
    return {"ok":True}


@app.post("/api/collections/{collection_id}/models", dependencies=[Depends(auth)])
async def collection_add_models(collection_id: str, request: Request):
    d=await request.json(); ids=[str(x) for x in d.get("model_ids",[]) if x]
    with db() as conn:
        c=conn.execute("SELECT kind FROM collections WHERE id=?",(collection_id,)).fetchone()
        if not c: raise HTTPException(404,"Collection not found")
        if c["kind"]!="manual": raise HTTPException(400,"Smart collections are filter-driven")
        ts=now_iso()
        for mid in ids:
            if conn.execute("SELECT 1 FROM models WHERE id=?",(mid,)).fetchone():
                conn.execute("INSERT OR IGNORE INTO collection_models(collection_id,model_id,added_at) VALUES(?,?,?)",(collection_id,mid,ts))
    return collection_detail(collection_id)


@app.delete("/api/collections/{collection_id}/models", dependencies=[Depends(auth)])
async def collection_remove_models(collection_id: str, request: Request):
    d=await request.json(); ids=[str(x) for x in d.get("model_ids",[]) if x]
    if ids:
        placeholders=','.join('?' for _ in ids)
        with db() as conn: conn.execute(f"DELETE FROM collection_models WHERE collection_id=? AND model_id IN ({placeholders})",[collection_id]+ids)
    return {"ok":True}


def crud_table(table: str, default_order: str = "created_at DESC"):
    with db() as conn:
        return [rowdict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY {default_order}").fetchall()]


@app.get("/api/projects", dependencies=[Depends(auth)])
def projects():
    with db() as conn:
        rows = conn.execute("""SELECT p.*, COUNT(pm.model_id) model_count, GROUP_CONCAT(pm.model_id) model_ids FROM projects p LEFT JOIN project_models pm ON p.id=pm.project_id GROUP BY p.id ORDER BY p.updated_at DESC""").fetchall()
    out=[]
    for r in rows:
        d=rowdict(r); d["model_ids"]=[x for x in (d.get("model_ids") or "").split(",") if x][:3]; out.append(d)
    return out


@app.post("/api/projects", dependencies=[Depends(auth)])
async def create_project(request: Request):
    d = await request.json(); pid = str(uuid.uuid4()); ts = now_iso()
    with db() as conn:
        conn.execute("INSERT INTO projects(id,name,description,status,tags,due_date,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                     (pid, d.get("name") or "Untitled project", d.get("description", ""), d.get("status", "Planning"), json.dumps(normalize_tags(d.get("tags"))), d.get("due_date") or None, ts, ts))
        row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    return rowdict(row)


@app.get("/api/projects/{project_id}", dependencies=[Depends(auth)])
def project_detail(project_id: str):
    with db() as conn:
        p = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not p: raise HTTPException(404, "Project not found")
        models = conn.execute("""SELECT m.*,pm.quantity,pm.variant,pm.urgency,pm.importance,(pm.urgency+pm.importance) priority_score
          FROM project_models pm JOIN models m ON m.id=pm.model_id WHERE pm.project_id=?
          ORDER BY priority_score DESC,pm.urgency DESC,m.title""", (project_id,)).fetchall()
    out = rowdict(p); out["models"] = [rowdict(r) for r in models]; return out


@app.patch("/api/projects/{project_id}", dependencies=[Depends(auth)])
async def update_project(project_id: str, request: Request):
    """Update project metadata and, when supplied, replace its linked model plan atomically.

    Keeping links in the same transaction as the project save makes the editor behave like
    users expect: the bottom Save project button commits the whole project, not just the
    text fields while model choices are handled by a separate invisible workflow.
    """
    d = await request.json()
    allowed = {"name", "description", "status", "due_date"}
    sets: list[str] = []
    args: list[Any] = []
    for k in allowed:
        if k in d:
            sets.append(f"{k}=?")
            args.append((d[k] or None) if k == "due_date" else d[k])
    if "tags" in d:
        sets.append("tags=?")
        args.append(json.dumps(normalize_tags(d["tags"])))
    sets.append("updated_at=?")
    args.append(now_iso())

    links = d.get("models", None)
    normalized_links: list[tuple[str, int, str, int, int]] | None = None
    if links is not None:
        if not isinstance(links, list):
            raise HTTPException(400, "Project models must be a list")
        normalized_links = []
        seen: set[str] = set()
        for link in links:
            if not isinstance(link, dict) or not link.get("model_id"):
                raise HTTPException(400, "Each project model needs a model_id")
            mid = str(link["model_id"])
            if mid in seen:
                continue
            seen.add(mid)
            try:
                quantity = max(1, int(link.get("quantity", 1)))
            except (TypeError, ValueError):
                raise HTTPException(400, "Project model quantity must be a whole number")
            try:
                urgency = max(1, min(5, int(link.get("urgency", 3))))
                importance = max(1, min(5, int(link.get("importance", 3))))
            except (TypeError, ValueError):
                raise HTTPException(400, "Urgency and importance must be ratings from 1 to 5")
            normalized_links.append((mid, quantity, str(link.get("variant", "")).strip(), urgency, importance))

    with db() as conn:
        exists = conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "Project not found")

        if normalized_links is not None and normalized_links:
            ids = [x[0] for x in normalized_links]
            placeholders = ",".join("?" for _ in ids)
            found = {r["id"] for r in conn.execute(f"SELECT id FROM models WHERE id IN ({placeholders})", ids).fetchall()}
            missing = [mid for mid in ids if mid not in found]
            if missing:
                raise HTTPException(404, "One or more selected models no longer exist")

        conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", [*args, project_id])
        if normalized_links is not None:
            conn.execute("DELETE FROM project_models WHERE project_id=?", (project_id,))
            conn.executemany(
                "INSERT INTO project_models(project_id,model_id,quantity,variant,urgency,importance) VALUES(?,?,?,?,?,?)",
                [(project_id, mid, quantity, variant, urgency, importance) for mid, quantity, variant, urgency, importance in normalized_links],
            )
    return project_detail(project_id)


@app.delete("/api/projects/{project_id}", dependencies=[Depends(auth)])
def delete_project(project_id: str):
    with db() as conn: conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    return {"ok": True}


@app.post("/api/projects/{project_id}/models/{model_id}", dependencies=[Depends(auth)])
async def project_add_model(project_id: str, model_id: str, request: Request):
    d = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    try:
        quantity = max(1, int(d.get("quantity", 1)))
    except (TypeError, ValueError):
        raise HTTPException(400, "Quantity must be a whole number")
    with db() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise HTTPException(404, "Project not found")
        if not conn.execute("SELECT 1 FROM models WHERE id=?", (model_id,)).fetchone():
            raise HTTPException(404, "Model not found")
        try:
            urgency = max(1, min(5, int(d.get("urgency", 3))))
            importance = max(1, min(5, int(d.get("importance", 3))))
        except (TypeError, ValueError):
            raise HTTPException(400, "Urgency and importance must be ratings from 1 to 5")
        conn.execute("INSERT INTO project_models(project_id,model_id,quantity,variant,urgency,importance) VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,model_id) DO UPDATE SET quantity=excluded.quantity,variant=excluded.variant,urgency=excluded.urgency,importance=excluded.importance",
                     (project_id, model_id, quantity, str(d.get("variant", "")).strip(), urgency, importance))
    return project_detail(project_id)


@app.delete("/api/projects/{project_id}/models/{model_id}", dependencies=[Depends(auth)])
def project_remove_model(project_id: str, model_id: str):
    with db() as conn: conn.execute("DELETE FROM project_models WHERE project_id=? AND model_id=?", (project_id, model_id))
    return {"ok": True}



def create_material_record(conn: sqlite3.Connection, d: dict[str, Any]) -> dict[str, Any]:
    mid=str(uuid.uuid4()); ts=now_iso(); initial=float(d.get('initial_amount') or 1000); remaining=float(d.get('remaining_amount') if d.get('remaining_amount') is not None else initial)
    kind=d.get('kind','Filament'); unit=d.get('unit') or ('ml' if technology_family(kind)=='Resin' else 'g')
    code=d.get('inventory_code') or next_inventory_code(conn,'materials','LV-MAT')
    source_provider=str(d.get('source_provider') or '')
    source_key=str(d.get('source_key') or '')
    source_url=str(d.get('source_url') or '')
    source_snapshot=json.dumps(as_json_dict(d.get('source_snapshot')), separators=(',',':'))
    material_specs=as_json_dict(d.get('specs'))
    artwork=catalog_official_artwork(str(d.get('brand') or ''),str(d.get('name') or ''),str(d.get('material') or ''),kind,str(d.get('color') or ''))
    if artwork:
        d['source_image_url']=artwork['url']; d['product_url']=d.get('product_url') or artwork.get('product_url') or artwork['url']
        material_specs={**artwork.get('specs',{}),**material_specs}
    specs=json.dumps(material_specs, separators=(',',':'))
    source_imported_at=d.get('source_imported_at') or (ts if source_provider else None)
    conn.execute("""INSERT INTO materials(id,inventory_code,name,kind,material,brand,color,color_hex,density_g_cm3,diameter_mm,gtin,product_url,initial_amount,remaining_amount,unit,location,supplier,batch_lot,purchase_price,purchased_at,stock_status,notes,opened_at,source_provider,source_key,source_url,source_snapshot,source_imported_at,source_image_url,specs,custom_image_asset_id,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (mid,code,d.get('name') or f"{d.get('brand','')} {d.get('material','PLA')}".strip(),kind,d.get('material','PLA'),d.get('brand',''),d.get('color',''),d.get('color_hex','#808080'),d.get('density_g_cm3'),d.get('diameter_mm'),d.get('gtin',''),d.get('product_url',''),initial,remaining,unit,d.get('location',''),d.get('supplier',''),d.get('batch_lot',''),d.get('purchase_price'),d.get('purchased_at') or None,d.get('stock_status','Open'),d.get('notes',''),d.get('opened_at') or None,source_provider,source_key,source_url,source_snapshot,source_imported_at,d.get('source_image_url',''),specs,d.get('custom_image_asset_id',''),ts,ts))
    conn.execute("INSERT INTO material_transactions(id,material_id,kind,amount_delta,balance_after,note,created_at) VALUES(?,?,?,?,?,?,?)",(str(uuid.uuid4()),mid,'Opening balance',0,remaining,'Initial stock recorded',ts))
    _apply_bound_image(conn, 'material', 'materials', mid)
    return material_with_metrics(conn,conn.execute("SELECT * FROM materials WHERE id=?",(mid,)).fetchone())


def create_profile_record(conn: sqlite3.Connection, d: dict[str, Any]) -> dict[str, Any]:
    pid=str(uuid.uuid4()); ts=now_iso(); settings=as_json_dict(d.get('settings'))
    layer=d.get('layer_height') if d.get('layer_height') is not None else settings.get('layer_height_mm')
    source_provider=str(d.get('source_provider') or '')
    source_snapshot=json.dumps(as_json_dict(d.get('source_snapshot')), separators=(',',':'))
    source_imported_at=d.get('source_imported_at') or (ts if source_provider else None)
    conn.execute("""INSERT INTO profiles(id,name,technology,printer_id,material,layer_height,settings,notes,profile_origin,source_provider,source_key,source_url,source_snapshot,source_imported_at,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (pid,d.get('name') or 'Print profile',d.get('technology','FDM'),d.get('printer_id') or None,d.get('material',''),layer,json.dumps(settings),d.get('notes',''),d.get('profile_origin') or ('Recommended' if source_provider else 'Local'),source_provider,d.get('source_key',''),d.get('source_url',''),source_snapshot,source_imported_at,ts,ts))
    row=conn.execute("SELECT * FROM profiles WHERE id=?",(pid,)).fetchone()
    return rowdict(row)


def catalog_printer(printer_id: str = '') -> dict[str, Any] | None:
    if not printer_id: return None
    with db() as conn:
        row=conn.execute("SELECT * FROM printers WHERE id=?",(printer_id,)).fetchone()
    return rowdict(row) if row else None


@app.get("/api/catalog/providers", dependencies=[Depends(auth)])
def material_catalog_providers():
    return catalog_providers()


@app.get("/api/catalog/search", dependencies=[Depends(auth)])
def material_catalog_search(q: str='', provider: str='all', printer_id: str='', limit: int=40):
    if provider not in {'all','spoolman','openresin','manufacturer_resin'}: raise HTTPException(400,'Unknown material source')
    try:
        return catalog_search(q,provider,catalog_printer(printer_id),max(1,min(int(limit),80)))
    except Exception as exc:
        raise HTTPException(502,f'Material catalogue search failed: {exc}')


@app.get("/api/catalog/item", dependencies=[Depends(auth)])
def material_catalog_item(provider: str, key: str, printer_id: str=''):
    try:
        return catalog_detail(provider,key,catalog_printer(printer_id))
    except KeyError as exc:
        raise HTTPException(404,str(exc).strip("'"))
    except Exception as exc:
        raise HTTPException(502,f'Material source unavailable: {exc}')


@app.get("/api/catalog/image", dependencies=[Depends(auth)])
def material_catalog_image(provider: str, key: str, printer_id: str=''):
    try:
        payload, media_type = catalog_image(provider, key, catalog_printer(printer_id))
        return Response(content=payload, media_type=media_type, headers={"Cache-Control": "public, max-age=2592000"})
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'"))
    except Exception as exc:
        raise HTTPException(502, f'Material artwork unavailable: {exc}')


@app.post("/api/catalog/import", dependencies=[Depends(auth)])
async def material_catalog_import(request: Request):
    d=await request.json(); provider=str(d.get('provider') or ''); key=str(d.get('key') or ''); printer_id=str(d.get('printer_id') or '')
    try:
        item=catalog_detail(provider,key,catalog_printer(printer_id))
    except KeyError as exc:
        raise HTTPException(404,str(exc).strip("'"))
    except Exception as exc:
        raise HTTPException(502,f'Material source unavailable: {exc}')
    material_payload={**(item.get('material_payload') or {}),**as_json_dict(d.get('material_overrides'))}
    create_profile=bool(d.get('create_profile')) and bool(item.get('profile_payload'))
    profile_payload={**(item.get('profile_payload') or {}),**as_json_dict(d.get('profile_overrides'))}
    if create_profile:
        profile_payload['printer_id']=printer_id or profile_payload.get('printer_id') or None
    with db() as conn:
        material=create_material_record(conn,material_payload)
        profile=create_profile_record(conn,profile_payload) if create_profile else None
    return {'material':material,'profile':profile,'source':item.get('provider')}


@app.get("/api/materials", dependencies=[Depends(auth)])
def materials():
    with db() as conn:
        rows=conn.execute("SELECT * FROM materials ORDER BY CASE stock_status WHEN 'Open' THEN 0 WHEN 'Sealed' THEN 1 WHEN 'Empty' THEN 2 ELSE 3 END, updated_at DESC").fetchall()
        return [material_with_metrics(conn,r) for r in rows]

@app.get("/api/materials/{item_id}", dependencies=[Depends(auth)])
def material_detail(item_id: str):
    with db() as conn:
        row=conn.execute("SELECT * FROM materials WHERE id=?",(item_id,)).fetchone()
        if not row: raise HTTPException(404,"Material not found")
        out=material_with_metrics(conn,row)
        out['transactions']=[dict(r) for r in conn.execute("SELECT * FROM material_transactions WHERE material_id=? ORDER BY created_at DESC LIMIT 50",(item_id,)).fetchall()]
        out['recent_jobs']=[rowdict(r) for r in conn.execute("""SELECT j.id,j.name,j.status,j.result_rating,j.material_used,j.material_cost,j.settings_snapshot,j.completed_at,
          p.name printer_name,m.title model_title FROM jobs j LEFT JOIN printers p ON p.id=j.printer_id LEFT JOIN models m ON m.id=j.model_id
          WHERE j.material_id=? ORDER BY COALESCE(j.completed_at,j.created_at) DESC LIMIT 12""",(item_id,)).fetchall()]
        return out

@app.post("/api/materials", dependencies=[Depends(auth)])
async def create_material(request: Request):
    d=await request.json()
    with db() as conn: return create_material_record(conn,d)

@app.patch("/api/materials/{item_id}", dependencies=[Depends(auth)])
async def update_material(item_id: str, request: Request):
    d=await request.json(); allowed={'name','kind','material','brand','color','color_hex','density_g_cm3','diameter_mm','gtin','product_url','initial_amount','unit','location','supplier','batch_lot','purchase_price','purchased_at','stock_status','notes','opened_at'}; sets=[];args=[]
    for k in allowed:
        if k in d: sets.append(f"{k}=?"); args.append(d[k])
    sets.append('updated_at=?');args.append(now_iso());args.append(item_id)
    with db() as conn:
        if conn.execute(f"UPDATE materials SET {', '.join(sets)} WHERE id=?",args).rowcount==0: raise HTTPException(404,'Material not found')
        _bind_current_item_image(conn, 'material', 'materials', item_id)
        row=conn.execute("SELECT * FROM materials WHERE id=?",(item_id,)).fetchone(); return material_with_metrics(conn,row)

@app.post("/api/materials/{item_id}/adjust", dependencies=[Depends(auth)])
async def adjust_material(item_id: str, request: Request):
    d=await request.json(); amount=float(d.get('amount_delta') or 0)
    with db() as conn:
        if not conn.execute("SELECT 1 FROM materials WHERE id=?",(item_id,)).fetchone(): raise HTTPException(404,'Material not found')
        add_material_transaction(conn,item_id,amount,d.get('kind') or 'Manual adjustment',d.get('note',''))
        row=conn.execute("SELECT * FROM materials WHERE id=?",(item_id,)).fetchone(); return material_with_metrics(conn,row)

@app.get("/api/materials/{item_id}/image", dependencies=[Depends(auth)])
def material_image(item_id: str):
    with db() as conn:
        row=conn.execute("SELECT custom_image_asset_id,source_image_url,source_provider,source_key FROM materials WHERE id=?",(item_id,)).fetchone()
        if not row: raise HTTPException(404,'Material not found')
        if row['custom_image_asset_id']:
            return _custom_image_response(conn,row['custom_image_asset_id'])
        if not row['source_image_url']:
            raise HTTPException(404,'No image for this material')
        try:
            payload, media_type = catalog_official_image(row['source_image_url'])
            return Response(content=payload, media_type=media_type, headers={"Cache-Control": "public, max-age=2592000"})
        except Exception as exc:
            raise HTTPException(502, f'Material artwork unavailable: {exc}')


@app.post("/api/materials/{item_id}/image", dependencies=[Depends(auth)])
async def upload_material_image(item_id: str, file: UploadFile = File(...)):
    payload=await file.read()
    with db() as conn:
        row=conn.execute("SELECT * FROM materials WHERE id=?",(item_id,)).fetchone()
        if not row: raise HTTPException(404,'Material not found')
        asset_id=_store_custom_image(conn,payload)
        conn.execute("UPDATE materials SET custom_image_asset_id=?,updated_at=? WHERE id=?",(asset_id,now_iso(),item_id))
        row=conn.execute("SELECT * FROM materials WHERE id=?",(item_id,)).fetchone()
        _bind_current_item_image(conn,'material','materials',item_id)
        return material_with_metrics(conn,row)


@app.delete("/api/materials/{item_id}/image", dependencies=[Depends(auth)])
def clear_material_image(item_id: str):
    with db() as conn:
        if conn.execute("UPDATE materials SET custom_image_asset_id='',updated_at=? WHERE id=?",(now_iso(),item_id)).rowcount==0:
            raise HTTPException(404,'Material not found')
    return {'ok':True}


@app.get("/api/materials/{item_id}/qr", dependencies=[Depends(auth)])
def material_qr(item_id: str, request: Request):
    import qrcode
    with db() as conn:
        row=conn.execute("SELECT inventory_code FROM materials WHERE id=?",(item_id,)).fetchone()
    if not row: raise HTTPException(404,'Material not found')
    url=str(request.base_url).rstrip('/')+f"/?material={item_id}"
    img=qrcode.make(url); buf=io.BytesIO(); img.save(buf,format='PNG'); buf.seek(0)
    return StreamingResponse(buf,media_type='image/png',headers={'Content-Disposition':f'inline; filename="{row["inventory_code"]}.png"'})

@app.delete("/api/materials/{item_id}", dependencies=[Depends(auth)])
def delete_material(item_id: str):
    with db() as conn: conn.execute("DELETE FROM materials WHERE id=?",(item_id,))
    return {'ok':True}

def create_printer_record(conn: sqlite3.Connection, d: dict[str, Any]) -> dict[str, Any]:
    pid=str(uuid.uuid4()); ts=now_iso(); code=d.get('inventory_code') or next_inventory_code(conn,'printers','LV-PRN')
    source_provider=str(d.get('source_provider') or '')
    source_snapshot=json.dumps(as_json_dict(d.get('source_snapshot')), separators=(',',':'))
    source_imported_at=d.get('source_imported_at') or (ts if source_provider else None)
    nozzle_options=json.dumps(as_json_list(d.get('nozzle_options')), separators=(',',':'))
    capabilities=json.dumps(as_json_dict(d.get('capabilities')), separators=(',',':'))
    conn.execute("""INSERT INTO printers(id,inventory_code,name,technology,manufacturer,model,serial_number,location,purchased_at,purchase_price,printer_status,firmware_version,last_service_at,build_x,build_y,build_z,nozzle_mm,nozzle_options,resolution_x,resolution_y,xy_resolution_x_um,xy_resolution_y_um,screen_width_mm,screen_height_mm,capabilities,source_provider,source_key,source_url,source_license,source_snapshot,source_imported_at,source_image_url,custom_image_asset_id,notes,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (pid,code,d.get('name') or d.get('model') or '3D Printer',d.get('technology','FDM'),d.get('manufacturer',''),d.get('model',''),d.get('serial_number',''),d.get('location',''),d.get('purchased_at') or None,d.get('purchase_price'),d.get('printer_status','Active'),d.get('firmware_version',''),d.get('last_service_at') or None,d.get('build_x'),d.get('build_y'),d.get('build_z'),d.get('nozzle_mm'),nozzle_options,d.get('resolution_x'),d.get('resolution_y'),d.get('xy_resolution_x_um'),d.get('xy_resolution_y_um'),d.get('screen_width_mm'),d.get('screen_height_mm'),capabilities,source_provider,d.get('source_key',''),d.get('source_url',''),d.get('source_license',''),source_snapshot,source_imported_at,d.get('source_image_url',''),d.get('custom_image_asset_id',''),d.get('notes',''),ts,ts))
    _apply_bound_image(conn, 'printer', 'printers', pid)
    return printer_with_metrics(conn,conn.execute("SELECT * FROM printers WHERE id=?",(pid,)).fetchone())


@app.get("/api/printer-catalog/providers", dependencies=[Depends(auth)])
def open_printer_catalog_providers():
    return printer_catalog_providers()


@app.get("/api/printer-catalog/search", dependencies=[Depends(auth)])
def open_printer_catalog_search(q: str='', provider: str='all', technology: str='all', limit: int=30):
    if provider not in {'all','orca','uvtools','dragonfruit'}: raise HTTPException(400,'Unknown printer source')
    try:
        return printer_catalog_search(q,provider,technology,max(1,min(int(limit),50)))
    except Exception as exc:
        raise HTTPException(502,f'Printer catalogue search failed: {exc}')


@app.get("/api/printer-catalog/item", dependencies=[Depends(auth)])
def open_printer_catalog_item(provider: str, key: str):
    try:
        return printer_catalog_detail(provider,key)
    except KeyError as exc:
        raise HTTPException(404,str(exc).strip("'"))
    except Exception as exc:
        raise HTTPException(502,f'Printer source unavailable: {exc}')


@app.get("/api/printer-catalog/image", dependencies=[Depends(auth)])
def open_printer_catalog_image(provider: str, key: str):
    try:
        data, ctype=printer_catalog_image(provider,key)
        return Response(content=data,media_type=ctype,headers={'Cache-Control':'public, max-age=2592000, immutable'})
    except KeyError as exc:
        raise HTTPException(404,str(exc).strip("'"))
    except Exception as exc:
        raise HTTPException(502,f'Printer image unavailable: {exc}')


@app.post("/api/printer-catalog/import", dependencies=[Depends(auth)])
async def open_printer_catalog_import(request: Request):
    d=await request.json(); provider=str(d.get('provider') or ''); key=str(d.get('key') or '')
    try:
        item=printer_catalog_detail(provider,key)
    except KeyError as exc:
        raise HTTPException(404,str(exc).strip("'"))
    except Exception as exc:
        raise HTTPException(502,f'Printer source unavailable: {exc}')
    payload={
        'name':item.get('name'),'technology':item.get('technology'),'manufacturer':item.get('manufacturer'),'model':item.get('model'),
        'build_x':item.get('build_x'),'build_y':item.get('build_y'),'build_z':item.get('build_z'),'nozzle_mm':item.get('nozzle_mm'),
        'nozzle_options':item.get('nozzle_options') or [],'resolution_x':item.get('resolution_x'),'resolution_y':item.get('resolution_y'),
        'xy_resolution_x_um':item.get('xy_resolution_x_um'),'xy_resolution_y_um':item.get('xy_resolution_y_um'),
        'screen_width_mm':item.get('screen_width_mm'),'screen_height_mm':item.get('screen_height_mm'),'capabilities':item.get('capabilities') or {},
        'source_provider':provider,'source_key':key,'source_url':item.get('source_url') or '','source_license':item.get('source_license') or '',
        'source_snapshot':item.get('source_snapshot') or {},'source_imported_at':now_iso(),'source_image_url':item.get('image_url') or '',
    }
    payload.update(as_json_dict(d.get('overrides')))
    with db() as conn: printer=create_printer_record(conn,payload)
    return {'printer':printer,'source':item.get('provider')}


@app.get("/api/printers", dependencies=[Depends(auth)])
def printers():
    with db() as conn:
        return [printer_with_metrics(conn,r) for r in conn.execute("SELECT * FROM printers ORDER BY name COLLATE NOCASE").fetchall()]

@app.get("/api/printers/{item_id}", dependencies=[Depends(auth)])
def printer_detail(item_id: str):
    with db() as conn:
        row=conn.execute("SELECT * FROM printers WHERE id=?",(item_id,)).fetchone()
        if not row: raise HTTPException(404,'Printer not found')
        out=printer_with_metrics(conn,row)
        out['recent_jobs']=[rowdict(r) for r in conn.execute("SELECT id,name,status,result_rating,duration_minutes,completed_at FROM jobs WHERE printer_id=? ORDER BY COALESCE(completed_at,created_at) DESC LIMIT 10",(item_id,)).fetchall()]
        return out

@app.get("/api/printers/{item_id}/image", dependencies=[Depends(auth)])
def printer_image(item_id: str):
    with db() as conn:
        row=conn.execute("SELECT custom_image_asset_id,source_image_url,source_provider,source_key,manufacturer,model,name,technology FROM printers WHERE id=?",(item_id,)).fetchone()
        if not row: raise HTTPException(404,'Printer not found')
        if row['custom_image_asset_id']:
            return _custom_image_response(conn,row['custom_image_asset_id'])
    provider=row['source_provider']; key=row['source_key']; source_image=row['source_image_url']
    if not source_image:
        artwork=printer_local_image(row['manufacturer'],row['model'] or row['name'])
        if artwork: provider=artwork['provider_id']; key=artwork['key']; source_image=artwork['image_url']
    if not source_image: raise HTTPException(404,'No image for this printer')
    try:
        if provider in {'orca','uvtools','dragonfruit'} and key:
            data,ctype=printer_catalog_image(provider,key)
        else:
            data,ctype=printer_remote_image(source_image,f"owned:{item_id}:{provider}:{key}")
        return Response(content=data,media_type=ctype,headers={'Cache-Control':'public, max-age=2592000'})
    except Exception as exc:
        raise HTTPException(502,f'Printer image unavailable: {exc}')


@app.post("/api/printers/{item_id}/image", dependencies=[Depends(auth)])
async def upload_printer_image(item_id: str, file: UploadFile = File(...)):
    payload=await file.read()
    with db() as conn:
        row=conn.execute("SELECT * FROM printers WHERE id=?",(item_id,)).fetchone()
        if not row: raise HTTPException(404,'Printer not found')
        asset_id=_store_custom_image(conn,payload)
        conn.execute("UPDATE printers SET custom_image_asset_id=?,updated_at=? WHERE id=?",(asset_id,now_iso(),item_id))
        row=conn.execute("SELECT * FROM printers WHERE id=?",(item_id,)).fetchone()
        _bind_current_item_image(conn,'printer','printers',item_id)
        return printer_with_metrics(conn,row)


@app.delete("/api/printers/{item_id}/image", dependencies=[Depends(auth)])
def clear_printer_image(item_id: str):
    with db() as conn:
        if conn.execute("UPDATE printers SET custom_image_asset_id='',updated_at=? WHERE id=?",(now_iso(),item_id)).rowcount==0:
            raise HTTPException(404,'Printer not found')
    return {'ok':True}


@app.post("/api/printers", dependencies=[Depends(auth)])
async def create_printer(request: Request):
    d=await request.json()
    with db() as conn: return create_printer_record(conn,d)

@app.patch("/api/printers/{item_id}", dependencies=[Depends(auth)])
async def update_printer(item_id: str, request: Request):
    d=await request.json(); allowed={'name','technology','manufacturer','model','serial_number','location','purchased_at','purchase_price','printer_status','firmware_version','last_service_at','build_x','build_y','build_z','nozzle_mm','resolution_x','resolution_y','xy_resolution_x_um','xy_resolution_y_um','screen_width_mm','screen_height_mm','notes'};sets=[];args=[]
    for k in allowed:
        if k in d: sets.append(f"{k}=?");args.append(d[k])
    if 'nozzle_options' in d: sets.append('nozzle_options=?');args.append(json.dumps(as_json_list(d.get('nozzle_options'))))
    if 'capabilities' in d: sets.append('capabilities=?');args.append(json.dumps(as_json_dict(d.get('capabilities'))))
    sets.append('updated_at=?');args.append(now_iso());args.append(item_id)
    with db() as conn:
        if conn.execute(f"UPDATE printers SET {', '.join(sets)} WHERE id=?",args).rowcount==0: raise HTTPException(404,'Printer not found')
        _bind_current_item_image(conn, 'printer', 'printers', item_id)
        return printer_with_metrics(conn,conn.execute("SELECT * FROM printers WHERE id=?",(item_id,)).fetchone())

@app.delete("/api/printers/{item_id}", dependencies=[Depends(auth)])
def delete_printer(item_id: str):
    with db() as conn: conn.execute("DELETE FROM printers WHERE id=?",(item_id,))
    return {'ok':True}

@app.get("/api/profiles", dependencies=[Depends(auth)])
def profiles():
    with db() as conn:
        rows=conn.execute("""SELECT pr.*, COUNT(j.id) job_count, AVG(CASE WHEN j.result_rating IS NOT NULL THEN j.result_rating END) avg_rating,
          SUM(CASE WHEN j.status='Complete' THEN 1 ELSE 0 END) successes, SUM(CASE WHEN j.status IN ('Complete','Failed') THEN 1 ELSE 0 END) attempts
          FROM profiles pr LEFT JOIN jobs j ON j.profile_id=pr.id GROUP BY pr.id ORDER BY pr.name COLLATE NOCASE""").fetchall()
        out=[]
        for r in rows:
            d=rowdict(r); attempts=int(d.pop('attempts') or 0); successes=int(d.pop('successes') or 0); d['success_rate']=round(successes/attempts*100,1) if attempts else None
            d['avg_rating']=round(float(d['avg_rating']),2) if d.get('avg_rating') is not None else None; out.append(d)
        return out

@app.post("/api/profiles", dependencies=[Depends(auth)])
async def create_profile(request: Request):
    d=await request.json()
    with db() as conn: return create_profile_record(conn,d)

@app.patch("/api/profiles/{item_id}", dependencies=[Depends(auth)])
async def update_profile(item_id: str, request: Request):
    d=await request.json(); allowed={'name','technology','printer_id','material','layer_height','notes','profile_origin'};sets=[];args=[]
    for k in allowed:
        if k in d: sets.append(f"{k}=?");args.append(d[k] or None if k=='printer_id' else d[k])
    if 'settings' in d: sets.append('settings=?');args.append(json.dumps(as_json_dict(d['settings'])))
    sets.append('updated_at=?');args.append(now_iso());args.append(item_id)
    with db() as conn:
        if conn.execute(f"UPDATE profiles SET {', '.join(sets)} WHERE id=?",args).rowcount==0: raise HTTPException(404,'Profile not found')
    return next(x for x in profiles() if x['id']==item_id)

@app.delete("/api/profiles/{item_id}", dependencies=[Depends(auth)])
def delete_profile(item_id: str):
    with db() as conn: conn.execute("DELETE FROM profiles WHERE id=?",(item_id,))
    return {'ok':True}


TOOLPATH_EXTENSIONS = {'.gcode', '.bgcode', '.3mf', '.pm3'}


def _toolpath_text(path: Path) -> str:
    """Read useful slicer metadata without loading an entire large toolpath into RAM."""
    if zipfile.is_zipfile(path):
        chunks: list[str] = []
        total = 0
        with zipfile.ZipFile(path) as archive:
            preferred = sorted(
                (info for info in archive.infolist() if not info.is_dir() and Path(info.filename).suffix.lower() in {'.config', '.ini', '.txt', '.gcode', '.model', '.xml', '.json'}),
                key=lambda info: (0 if 'metadata/' in info.filename.lower() else 1, info.file_size),
            )
            for info in preferred:
                if total >= 8 * 1024 * 1024:
                    break
                # Slicers commonly put estimates at the end of generated G-code.
                # Keep both ends of large archive members while reading small
                # metadata/config members in full.
                with archive.open(info) as stream:
                    if info.file_size <= 2 * 1024 * 1024:
                        raw = stream.read()
                    else:
                        head = stream.read(1024 * 1024)
                        tail = b''
                        try:
                            stream.seek(max(0, info.file_size - 1024 * 1024))
                            tail = stream.read(1024 * 1024)
                        except (AttributeError, OSError):
                            pass
                        raw = head + b'\n' + tail
                total += len(raw)
                chunks.append(raw.decode('utf-8', errors='ignore'))
        return '\n'.join(chunks)
    size = path.stat().st_size
    with path.open('rb') as stream:
        head = stream.read(min(size, 4 * 1024 * 1024))
        tail = b''
        if size > len(head):
            stream.seek(max(0, size - 4 * 1024 * 1024))
            tail = stream.read(4 * 1024 * 1024)
    return (head + b'\n' + tail).decode('utf-8', errors='ignore')


def _line_numbers(text: str, labels: list[str]) -> list[float]:
    for label in labels:
        patterns = [
            rf'(?im)^\s*;?\s*{label}\s*[:=]\s*([^\r\n;]+)',
            rf'(?is)"(?:{label})"\s*:\s*(?:\[\s*)?"?(-?\d+(?:\.\d+)?%?)',
            rf'(?is)\b(?:{label})\s*=\s*"([^"]+)"',
            rf'(?is)key\s*=\s*"(?:{label})"\s+value\s*=\s*"([^"]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return [float(value) for value in re.findall(r'-?\d+(?:\.\d+)?', match.group(1))]
    return []


def _first_number(text: str, labels: list[str]) -> float | None:
    values = _line_numbers(text, labels)
    return values[0] if values else None


def _duration_minutes(text: str) -> int | None:
    seconds = _first_number(text, [r'TIME', r'print_time', r'total_print_time', r'prediction'])
    if seconds and seconds > 0:
        return max(1, int(seconds / 60 + 0.5))
    match = re.search(r'(?im)estimated\s+printing\s+time[^=:\r\n]*[:=]\s*([^\r\n]+)', text)
    if not match:
        return None
    value = match.group(1).lower()
    hours = float(re.search(r'(\d+(?:\.\d+)?)\s*h', value).group(1)) if re.search(r'(\d+(?:\.\d+)?)\s*h', value) else 0
    minutes = float(re.search(r'(\d+(?:\.\d+)?)\s*m', value).group(1)) if re.search(r'(\d+(?:\.\d+)?)\s*m', value) else 0
    seconds_value = float(re.search(r'(\d+(?:\.\d+)?)\s*s', value).group(1)) if re.search(r'(\d+(?:\.\d+)?)\s*s', value) else 0
    total = hours * 60 + minutes + seconds_value / 60
    return max(1, int(total + 0.5)) if total else None


def _pm3_metadata(path: Path) -> dict[str, Any] | None:
    """Read Anycubic PM3's bounded named tables without decoding layer images."""
    with path.open('rb') as stream:
        lead = stream.read(160)
        if len(lead) < 152 or lead[:8] != b'ANYCUBIC':
            return None
        version = struct.unpack_from('<I', lead, 12)[0]
        header_offset = struct.unpack_from('<I', lead, 20)[0]
        extra_offset = struct.unpack_from('<I', lead, 40)[0]
        machine_offset = struct.unpack_from('<I', lead, 44)[0]
        if not 0 <= header_offset < path.stat().st_size - 16:
            return None
        stream.seek(header_offset)
        table = stream.read(16)
        if table[:6] != b'HEADER':
            return None
        payload_size = struct.unpack_from('<I', table, 12)[0]
        if payload_size < 84 or payload_size > 4096:
            return None
        payload = stream.read(payload_size)

        extra_payload = b''
        if 0 <= extra_offset < path.stat().st_size - 16:
            stream.seek(extra_offset)
            extra_table = stream.read(16)
            if extra_table[:5] == b'EXTRA':
                extra_size = min(struct.unpack_from('<I', extra_table, 12)[0], 4096)
                extra_payload = stream.read(extra_size)

        machine_name = ''
        if 0 <= machine_offset < path.stat().st_size - 16:
            stream.seek(machine_offset)
            machine_table = stream.read(16)
            if machine_table[:7] == b'MACHINE':
                machine_size = min(struct.unpack_from('<I', machine_table, 12)[0], 4096)
                machine_raw = stream.read(machine_size)
                machine_name = machine_raw.split(b'\0', 1)[0].decode('utf-8', errors='ignore').strip()

    def finite_float(offset: int, minimum: float=0, maximum: float=1_000_000) -> float | None:
        if offset + 4 > len(payload):
            return None
        value = struct.unpack_from('<f', payload, offset)[0]
        return value if math.isfinite(value) and minimum <= value <= maximum else None

    # PM3 follows Photon Workshop's HEADER layout. The first float is XY
    # pixel size (microns), not bottom exposure; newer files append transition
    # and two-stage motion values after the original header.
    pixel_size_um = finite_float(0, 1, 1000)
    volume = finite_float(36, 0.001, 1_000_000)
    duration_seconds = struct.unpack_from('<I', payload, 68)[0] if len(payload) >= 72 else 0
    bottom_layers_value = finite_float(20, 0, 10_000)
    bottom_layers = int(round(bottom_layers_value)) if bottom_layers_value is not None else 0
    transition_layers = struct.unpack_from('<I', payload, 72)[0] if len(payload) >= 76 else 0
    settings = {
        'pixel_size_um': pixel_size_um,
        'layer_height_mm': finite_float(4, 0.001, 10),
        'normal_exposure_s': finite_float(8, 0, 10_000),
        'light_off_delay_s': finite_float(12, 0, 10_000),
        'bottom_exposure_s': finite_float(16, 0, 10_000),
        'bottom_layers': bottom_layers if 0 < bottom_layers < 10_000 else None,
        'transition_layers': transition_layers if 0 < transition_layers < 10_000 else None,
        'lift_distance_mm': finite_float(24, 0, 1000),
        'lift_speed_mms': finite_float(28, 0, 1000),
        'retract_speed_mms': finite_float(32, 0, 1000),
        'anti_aliasing': struct.unpack_from('<I', payload, 40)[0] if len(payload) >= 44 else None,
    }
    # The optional PM3 EXTRA section extends the recipe. These are kept as
    # their own values instead of overwriting the compatible HEADER motion.
    if len(extra_payload) >= 24:
        extra_values=[struct.unpack_from('<f',extra_payload,offset)[0] for offset in range(4,24,4)]
        if all(math.isfinite(value) and 0 <= value <= 1000 for value in extra_values):
            settings.update({
                'lift_distance_2_mm': extra_values[0],
                'lift_speed_2_mms': extra_values[1],
                'retract_distance_mm': extra_values[2],
                'retract_speed_2_mms': extra_values[3],
                'wait_after_lift_s': extra_values[4],
            })
    return {
        'technology': 'Resin',
        'slicer': 'Anycubic PM3 format',
        'format_version': version,
        'printer_name': machine_name,
        'duration_minutes': max(1, int(duration_seconds / 60 + 0.5)) if duration_seconds else None,
        'material_volume_ml': volume,
        'settings': {key: round(value, 4) if isinstance(value, float) else value for key, value in settings.items() if value is not None},
    }


def _first_text_value(text: str, keys: list[str]) -> str:
    for key in keys:
        patterns = [
            rf'(?is)"{key}"\s*:\s*"([^"]+)"',
            rf'(?is)"{key}"\s*:\s*\[\s*"([^"]+)"',
            rf'(?is)\b{key}\s*=\s*"([^"]+)"',
            rf'(?is)key\s*=\s*"{key}"\s+value\s*=\s*"([^"]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
    return ''


def inspect_toolpath_file(path: Path, original_name: str) -> dict[str, Any]:
    pm3 = _pm3_metadata(path) if path.suffix.lower() == '.pm3' else None
    text = _toolpath_text(path)
    lower = text.lower()
    slicer = 'Unknown slicer'
    for needle, label in [('orcaslicer', 'OrcaSlicer'), ('prusaslicer', 'PrusaSlicer'), ('bambu studio', 'Bambu Studio'), ('cura', 'Cura'), ('superslicer', 'SuperSlicer')]:
        if needle in lower:
            slicer = label
            break
    if 'x-bbl-client-' in lower or 'printer_settings_id' in lower:
        slicer = 'Bambu Studio'

    technology = 'Resin' if pm3 else ('Resin' if re.search(r'(?i)printer_technology[^\r\n]{0,30}(?:sla|msla|dlp)', text) else 'FDM')
    printer_name = _first_text_value(text, [r'printer_model', r'printer_name', r'machine_name'])
    material_name = _first_text_value(text, [r'filament_settings_id', r'default_filament_profile', r'filament_type', r'material_name'])

    length_values = _line_numbers(text, [r'filament\s+used\s*\[mm\]', r'total\s+filament\s+used\s*\[mm\]', r'MATERIAL'])
    filament_length_mm = sum(value for value in length_values if value > 0) or None
    filament_nodes = re.findall(r'(?is)<filament\b[^>]*>', text)
    xml_metres = [float(value) for node in filament_nodes for value in re.findall(r'\bused_m="(\d+(?:\.\d+)?)"', node)]
    xml_grams = [float(value) for node in filament_nodes for value in re.findall(r'\bused_g="(\d+(?:\.\d+)?)"', node)]
    if xml_metres:
        filament_length_mm = sum(xml_metres) * 1000
    if filament_length_mm is None:
        metres = re.search(r'(?im)filament\s+used\s*:\s*(\d+(?:\.\d+)?)\s*m\b', text)
        if metres:
            filament_length_mm = float(metres.group(1)) * 1000
    volume_values = _line_numbers(text, [r'filament\s+used\s*\[cm3\]', r'filament\s+used\s*\[cm\^3\]', r'material_volume(?:_ml)?'])
    material_volume_ml = sum(value for value in volume_values if value > 0) or None
    weight_values = _line_numbers(text, [r'filament\s+used\s*\[g\]', r'total\s+filament\s+used\s*\[g\]', r'filament_weight'])
    material_weight_g = sum(value for value in weight_values if value > 0) or None
    if xml_grams:
        material_weight_g = sum(xml_grams)
    diameter = _first_number(text, [r'filament_diameter']) or 1.75
    density = _first_number(text, [r'filament_density', r'material_density'])
    volume_estimated = False
    if material_volume_ml is None and filament_length_mm:
        material_volume_ml = math.pi * (diameter / 2) ** 2 * filament_length_mm / 1000
        volume_estimated = True
    if material_weight_g is None and material_volume_ml and density:
        material_weight_g = material_volume_ml * density

    settings: dict[str, Any] = {}
    setting_sources = {
        'layer_height_mm': [r'layer_height'],
        'first_layer_height_mm': [r'initial_layer_print_height', r'first_layer_height'],
        'first_layer_temp_c': [r'first_layer_temperature', r'first_layer_nozzle_temperature', r'nozzle_temperature_initial_layer'],
        'nozzle_temp_c': [r'temperature', r'nozzle_temperature'],
        'bed_temp_c': [r'bed_temperature', r'first_layer_bed_temperature'],
        'print_speed_mms': [r'perimeter_speed', r'print_speed'],
        'outer_wall_speed_mms': [r'external_perimeter_speed', r'outer_wall_speed'],
        'inner_wall_speed_mms': [r'inner_wall_speed'],
        'infill_speed_mms': [r'sparse_infill_speed', r'infill_speed'],
        'solid_infill_speed_mms': [r'internal_solid_infill_speed', r'solid_infill_speed'],
        'top_surface_speed_mms': [r'top_surface_speed', r'top_solid_infill_speed'],
        'first_layer_speed_mms': [r'initial_layer_speed', r'first_layer_speed'],
        'travel_speed_mms': [r'travel_speed'],
        'acceleration_mms2': [r'normal_printing_acceleration', r'default_acceleration'],
        'travel_acceleration_mms2': [r'travel_acceleration'],
        'retraction_distance_mm': [r'retract_length', r'retraction_distance'],
        'retraction_speed_mms': [r'retract_speed', r'retraction_speed'],
        'fan_percent': [r'max_fan_speed', r'fan_speed'],
        'flow_percent': [r'filament_flow_ratio', r'print_flow_ratio', r'flow_ratio', r'extrusion_multiplier'],
        'wall_count': [r'wall_loops', r'perimeters'],
        'top_layers': [r'top_shell_layers', r'top_solid_layers'],
        'bottom_layers_fdm': [r'bottom_shell_layers', r'bottom_solid_layers'],
        'infill_percent': [r'sparse_infill_density', r'infill_sparse_density', r'fill_density'],
        'nozzle_mm': [r'nozzle_diameter'],
        'line_width_mm': [r'line_width', r'extrusion_width'],
        'first_layer_line_width_mm': [r'initial_layer_line_width', r'first_layer_extrusion_width'],
        'support_density_percent': [r'support_density'],
        'support_speed_mms': [r'support_speed', r'support_material_speed'],
        'support_interface_layers': [r'support_interface_layers'],
        'brim_width_mm': [r'brim_width'],
        'skirt_loops': [r'skirt_loops', r'skirts'],
        'max_volumetric_speed_mm3s': [r'filament_max_volumetric_speed', r'max_volumetric_speed'],
    }
    for key, labels in setting_sources.items():
        value = _first_number(text, labels)
        if value is not None:
            if key in {'flow_percent'} and value <= 2:
                value *= 100
            settings[key] = round(value, 4)
    if 'nozzle_temp_c' not in settings:
        commands = re.findall(r'(?im)^\s*M(?:104|109)\s+[^\r\n]*?S(\d+(?:\.\d+)?)', text)
        if commands:
            settings['nozzle_temp_c'] = float(commands[-1])
    if 'bed_temp_c' not in settings:
        configured_bed = _first_number(text, [r'hot_plate_temp', r'textured_plate_temp', r'bed_temperature_initial_layer'])
        if configured_bed is not None and configured_bed > 0:
            settings['bed_temp_c'] = configured_bed
    if 'bed_temp_c' not in settings:
        commands = re.findall(r'(?im)^\s*M(?:140|190)\s+[^\r\n]*?S(\d+(?:\.\d+)?)', text)
        if commands:
            settings['bed_temp_c'] = float(commands[-1])
    elif settings.get('bed_temp_c', 0) <= 0:
        configured_bed = _first_number(text, [r'hot_plate_temp', r'textured_plate_temp', r'bed_temperature_initial_layer'])
        if configured_bed is not None and configured_bed > 0:
            settings['bed_temp_c'] = configured_bed

    duration_minutes = _duration_minutes(text)
    if pm3:
        slicer = pm3['slicer']
        printer_name = pm3.get('printer_name') or printer_name
        duration_minutes = pm3.get('duration_minutes') or duration_minutes
        material_volume_ml = pm3.get('material_volume_ml') or material_volume_ml
        settings = {**settings, **pm3.get('settings', {})}

    warnings: list[str] = []
    if not text.strip():
        warnings.append('This file did not contain readable slicer metadata.')
    if material_volume_ml is None and material_weight_g is None:
        warnings.append('Material usage was not present in a recognised field.')
    if not settings:
        warnings.append('No recognised print parameters were found.')
    return {
        'original_name': Path(original_name).name,
        'extension': path.suffix.lower(),
        'size_bytes': path.stat().st_size,
        'slicer': slicer,
        'technology': technology,
        'printer_name': printer_name or None,
        'material_name': material_name or None,
        'format_version': pm3.get('format_version') if pm3 else None,
        'duration_minutes': duration_minutes,
        'filament_length_mm': round(filament_length_mm, 2) if filament_length_mm else None,
        'filament_diameter_mm': round(diameter, 3) if filament_length_mm else None,
        'filament_density_g_cm3': round(density, 4) if density else None,
        'material_volume_ml': round(material_volume_ml, 3) if material_volume_ml else None,
        'material_weight_g': round(material_weight_g, 3) if material_weight_g else None,
        'volume_estimated': volume_estimated,
        'settings': settings,
        'warnings': warnings,
    }


def _setup_match_score(hint: str, values: list[Any]) -> int:
    normal = lambda value: re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()
    wanted = normal(hint)
    if not wanted:
        return 0
    joined = ' '.join(normal(value) for value in values if value)
    if wanted == joined:
        return 1000
    score = 500 if wanted in joined or joined in wanted else 0
    score += sum(20 for token in set(wanted.split()) if len(token) > 1 and token in joined.split())
    return score


def _toolpath_setup_suggestions(metadata: dict[str, Any]) -> dict[str, Any]:
    technology = str(metadata.get('technology') or 'FDM')
    resin = technology.lower() == 'resin'
    with db() as conn:
        printer_rows = [dict(row) for row in conn.execute("SELECT * FROM printers ORDER BY CASE printer_status WHEN 'Active' THEN 0 ELSE 1 END, name COLLATE NOCASE").fetchall()]
        compatible_printers = [row for row in printer_rows if bool(re.search(r'resin|msla|sla|dlp', str(row.get('technology') or ''), re.I)) == resin]
        printer = max(compatible_printers, key=lambda row: (_setup_match_score(str(metadata.get('printer_name') or ''), [row.get('name'), row.get('manufacturer'), row.get('model')]), 1 if row.get('printer_status') == 'Active' else 0), default=None)

        material_rows = [dict(row) for row in conn.execute("SELECT * FROM materials WHERE stock_status NOT IN ('Empty','Archived') ORDER BY CASE stock_status WHEN 'Open' THEN 0 ELSE 1 END, updated_at DESC").fetchall()]
        def is_resin_material(row: dict[str, Any]) -> bool:
            identity = ' '.join(str(row.get(key) or '') for key in ('kind','material','name'))
            return bool(re.search(r'resin', identity, re.I)) or str(row.get('unit') or '').lower() == 'ml'
        compatible_materials = [row for row in material_rows if is_resin_material(row) == resin]
        material = max(compatible_materials, key=lambda row: _setup_match_score(str(metadata.get('material_name') or ''), [row.get('name'), row.get('brand'), row.get('material'), row.get('color')]), default=None)

        profile_rows = [dict(row) for row in conn.execute("SELECT * FROM profiles ORDER BY updated_at DESC").fetchall()]
        compatible_profiles = [row for row in profile_rows if bool(re.search(r'resin|msla|sla|dlp', str(row.get('technology') or ''), re.I)) == resin and (not row.get('printer_id') or not printer or row.get('printer_id') == printer.get('id'))]
        profile = max(compatible_profiles, key=lambda row: ((200 if printer and row.get('printer_id') == printer.get('id') else 0) + _setup_match_score(str(metadata.get('material_name') or ''), [row.get('material'), row.get('name')])), default=None)
    return {
        'suggested_printer_id': printer.get('id') if printer else None,
        'suggested_printer_name': printer.get('name') if printer else None,
        'suggested_material_id': material.get('id') if material else None,
        'suggested_material_name': material.get('name') if material else None,
        'suggested_profile_id': profile.get('id') if profile else None,
        'suggested_profile_name': profile.get('name') if profile else None,
    }


def _consume_toolpath_upload(token: str, job_id: str) -> tuple[str, dict[str, Any]]:
    if not re.fullmatch(r'[a-f0-9-]{36}', str(token or '')):
        raise HTTPException(422, 'The inspected print file token is invalid')
    metadata_path = TOOLPATH_UPLOAD_DIR / f'{token}.json'
    if not metadata_path.exists():
        raise HTTPException(410, 'The inspected print file has expired; choose it again')
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    staged = TOOLPATH_UPLOAD_DIR / f"{token}{metadata['extension']}"
    if not staged.exists():
        raise HTTPException(410, 'The inspected print file is missing; choose it again')
    stored_name = f"{job_id}{metadata['extension']}"
    shutil.move(str(staged), TOOLPATH_DIR / stored_name)
    metadata_path.unlink(missing_ok=True)
    return stored_name, metadata


@app.post('/api/jobs/toolpath/inspect', dependencies=[Depends(auth)])
async def inspect_job_toolpath(file: UploadFile = File(...)):
    original_name = Path(file.filename or 'print.gcode').name
    ext = Path(original_name).suffix.lower()
    if ext not in TOOLPATH_EXTENSIONS:
        raise HTTPException(415, 'Use a G-code, BGCODE, 3MF or PM3 print file')
    token = str(uuid.uuid4())
    staged = TOOLPATH_UPLOAD_DIR / f'{token}{ext}'
    size = 0
    try:
        with staged.open('wb') as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 1024 * 1024 * 1024:
                    raise HTTPException(413, 'Print files must be 1 GB or smaller')
                target.write(chunk)
        metadata = inspect_toolpath_file(staged, original_name)
        metadata.update(_toolpath_setup_suggestions(metadata))
        metadata['token'] = token
        (TOOLPATH_UPLOAD_DIR / f'{token}.json').write_text(json.dumps(metadata), encoding='utf-8')
        return metadata
    except Exception:
        staged.unlink(missing_ok=True)
        (TOOLPATH_UPLOAD_DIR / f'{token}.json').unlink(missing_ok=True)
        raise


def job_select(where: str='', args: tuple|list=()):
    with db() as conn:
        rows=conn.execute(f"""SELECT j.*,m.title model_title,p.name printer_name,p.technology printer_technology,mat.name material_name,mat.unit material_unit,mat.inventory_code material_inventory_code,pr.name profile_name,proj.name project_name
          FROM jobs j LEFT JOIN models m ON m.id=j.model_id LEFT JOIN printers p ON p.id=j.printer_id LEFT JOIN materials mat ON mat.id=j.material_id
          LEFT JOIN profiles pr ON pr.id=j.profile_id LEFT JOIN projects proj ON proj.id=j.project_id {where}
          ORDER BY COALESCE(j.completed_at,j.started_at,j.created_at) DESC""",args).fetchall()
        out=[rowdict(r) for r in rows]
        if out:
            job_ids=[item['id'] for item in out];placeholders=','.join('?' for _ in job_ids)
            linked=conn.execute(f"""SELECT jm.job_id,jm.model_id,jm.quantity,m.title,m.original_filename
              FROM job_models jm JOIN models m ON m.id=jm.model_id
              WHERE jm.job_id IN ({placeholders}) ORDER BY jm.rowid""",tuple(job_ids)).fetchall()
            by_job={job_id:[] for job_id in job_ids}
            for row in linked: by_job[row['job_id']].append({'model_id':row['model_id'],'quantity':int(row['quantity'] or 1),'title':row['title'],'original_filename':row['original_filename']})
            for item in out:
                item['models']=by_job[item['id']]
                item['model_quantity']=sum(link['quantity'] for link in item['models'])
                if item['models'] and not item.get('model_title'): item['model_title']=item['models'][0]['title']
        return out

@app.get("/api/jobs", dependencies=[Depends(auth)])
def jobs(status: str=''): return job_select('WHERE j.status=?',(status,)) if status else job_select()

@app.get("/api/jobs/insights/recipe", dependencies=[Depends(auth)])
def job_recipe_insights(model_id: str='', material_id: str='', printer_id: str=''):
    where=["j.status IN ('Complete','Failed')"];args=[]
    for field,value in [('model_id',model_id),('material_id',material_id),('printer_id',printer_id)]:
        if value: where.append(f'j.{field}=?');args.append(value)
    attempts=job_select('WHERE '+' AND '.join(where),args)
    completed=[j for j in attempts if j['status']=='Complete']; rated=[j for j in attempts if j.get('result_rating') is not None]
    best=sorted(rated,key=lambda j:(float(j.get('result_rating') or 0),1 if j['status']=='Complete' else 0),reverse=True)[0] if rated else (completed[0] if completed else None)
    return {'attempts':len(attempts),'success_rate':round(len(completed)/len(attempts)*100,1) if attempts else None,'avg_rating':round(sum(float(j['result_rating']) for j in rated)/len(rated),2) if rated else None,'best':best,'recent':attempts[:8]}

@app.get("/api/jobs/{item_id}", dependencies=[Depends(auth)])
def get_job(item_id: str):
    rows=job_select('WHERE j.id=?',(item_id,))
    if not rows: raise HTTPException(404,'Job not found')
    return rows[0]

@app.post("/api/jobs", dependencies=[Depends(auth)])
async def create_job(request: Request):
    d=await request.json();jid=str(uuid.uuid4());ts=now_iso();toolpath_file='';toolpath_metadata={}
    if d.get('toolpath_token'):
        toolpath_file,toolpath_metadata=_consume_toolpath_upload(str(d['toolpath_token']),jid)
    try:
        with db() as conn:
            imported_settings=as_json_dict(toolpath_metadata.get('settings'))
            settings=snapshot_settings(conn,d.get('profile_id'),{**imported_settings,**as_json_dict(d.get('settings_snapshot'))})
            material_used=d.get('material_used')
            if material_used is None and toolpath_metadata:
                material=conn.execute("SELECT unit,density_g_cm3 FROM materials WHERE id=?",(d.get('material_id'),)).fetchone() if d.get('material_id') else None
                volume=toolpath_metadata.get('material_volume_ml');weight=toolpath_metadata.get('material_weight_g')
                if material and material['unit']=='ml': material_used=volume
                elif material and material['unit']=='g': material_used=weight or (float(volume)*float(material['density_g_cm3']) if volume and material['density_g_cm3'] else None)
                else: material_used=weight or volume
            manifest=d.get('models') if isinstance(d.get('models'),list) else []
            primary_model_id=(next((str(item.get('model_id')) for item in manifest if isinstance(item,dict) and item.get('model_id')),None) or d.get('model_id') or None)
            conn.execute("""INSERT INTO jobs(id,name,project_id,model_id,printer_id,material_id,profile_id,technology,status,duration_minutes,material_used,settings_snapshot,toolpath_file,toolpath_original_name,toolpath_size_bytes,toolpath_metadata,result_rating,result_metrics,failure_reason,failure_tags,notes,started_at,completed_at,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (jid,d.get('name') or 'Print job',d.get('project_id') or None,primary_model_id,d.get('printer_id') or None,d.get('material_id') or None,d.get('profile_id') or None,d.get('technology') or toolpath_metadata.get('technology') or ('FDM' if toolpath_file else ''),d.get('status','Queued'),d.get('duration_minutes') if d.get('duration_minutes') is not None else toolpath_metadata.get('duration_minutes'),material_used,json.dumps(settings),toolpath_file,toolpath_metadata.get('original_name',''),int(toolpath_metadata.get('size_bytes') or 0),json.dumps(toolpath_metadata),d.get('result_rating'),json.dumps(as_json_dict(d.get('result_metrics'))),d.get('failure_reason',''),json.dumps(as_json_list(d.get('failure_tags'))),d.get('notes',''),d.get('started_at') or None,d.get('completed_at') or None,ts,ts))
            replace_job_models(conn,jid,manifest,primary_model_id)
            sync_job_model_count(conn,jid);sync_job_stock(conn,jid)
    except Exception:
        if toolpath_file: (TOOLPATH_DIR/toolpath_file).unlink(missing_ok=True)
        raise
    return get_job(jid)

@app.patch("/api/jobs/{item_id}", dependencies=[Depends(auth)])
async def update_job(item_id: str, request: Request):
    d=await request.json(); allowed={'name','project_id','model_id','printer_id','material_id','profile_id','technology','status','duration_minutes','material_used','result_rating','failure_reason','notes','started_at','completed_at'};sets=[];args=[]
    with db() as conn:
        if not conn.execute("SELECT 1 FROM jobs WHERE id=?",(item_id,)).fetchone(): raise HTTPException(404,'Job not found')
        for k in allowed:
            if k in d: sets.append(f"{k}=?");args.append(d[k] or None if k.endswith('_id') else d[k])
        if 'models' in d:
            manifest=replace_job_models(conn,item_id,d.get('models'),d.get('model_id'))
            primary_model_id=manifest[0]['model_id'] if manifest else None
            if 'model_id' not in d: sets.append('model_id=?');args.append(primary_model_id)
        if 'settings_snapshot' in d: sets.append('settings_snapshot=?');args.append(json.dumps(snapshot_settings(conn,d.get('profile_id'),d['settings_snapshot'])))
        if 'result_metrics' in d: sets.append('result_metrics=?');args.append(json.dumps(as_json_dict(d['result_metrics'])))
        if 'failure_tags' in d: sets.append('failure_tags=?');args.append(json.dumps(as_json_list(d['failure_tags'])))
        sets.append('updated_at=?');args.append(now_iso());args.append(item_id)
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?",args);sync_job_model_count(conn,item_id);sync_job_stock(conn,item_id)
    return get_job(item_id)

@app.post("/api/jobs/{item_id}/repeat", dependencies=[Depends(auth)])
def repeat_job(item_id: str):
    source=get_job(item_id);jid=str(uuid.uuid4());ts=now_iso()
    with db() as conn:
        conn.execute("""INSERT INTO jobs(id,name,project_id,model_id,printer_id,material_id,profile_id,technology,status,settings_snapshot,notes,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(jid,f"{source['name']} — repeat",source.get('project_id'),source.get('model_id'),source.get('printer_id'),source.get('material_id'),source.get('profile_id'),source.get('technology') or source.get('printer_technology') or '', 'Queued',json.dumps(source.get('settings_snapshot') or {}),'Repeated from a previous print recipe',ts,ts))
        replace_job_models(conn,jid,source.get('models'),source.get('model_id'))
    return get_job(jid)

@app.post("/api/jobs/{item_id}/photo", dependencies=[Depends(auth)])
async def upload_job_photo(item_id: str, file: UploadFile = File(...)):
    ext=Path(file.filename or 'result.jpg').suffix.lower()
    if ext not in {'.jpg','.jpeg','.png','.webp'}: raise HTTPException(415,'Use JPG, PNG or WEBP')
    with db() as conn:
        row=conn.execute("SELECT result_photo FROM jobs WHERE id=?",(item_id,)).fetchone()
        if not row: raise HTTPException(404,'Job not found')
    name=f'{item_id}{ext}';out=RESULT_DIR/name
    if row['result_photo']: (RESULT_DIR/row['result_photo']).unlink(missing_ok=True)
    with out.open('wb') as dst:
        while chunk:=await file.read(1024*1024): dst.write(chunk)
    with db() as conn: conn.execute("UPDATE jobs SET result_photo=?,updated_at=? WHERE id=?",(name,now_iso(),item_id))
    return {'ok':True,'file':name}

@app.get("/api/jobs/{item_id}/photo", dependencies=[Depends(auth)])
def job_photo(item_id: str):
    with db() as conn: row=conn.execute("SELECT result_photo FROM jobs WHERE id=?",(item_id,)).fetchone()
    if not row or not row['result_photo']: raise HTTPException(404,'No result photo')
    path=RESULT_DIR/row['result_photo']
    if not path.exists(): raise HTTPException(410,'Result photo is missing')
    return FileResponse(path,headers={'Cache-Control':'private, max-age=3600'})

@app.get("/api/jobs/{item_id}/toolpath", dependencies=[Depends(auth)])
def job_toolpath(item_id: str):
    with db() as conn: row=conn.execute("SELECT toolpath_file,toolpath_original_name FROM jobs WHERE id=?",(item_id,)).fetchone()
    if not row or not row['toolpath_file']: raise HTTPException(404,'No print file attached')
    path=TOOLPATH_DIR/row['toolpath_file']
    if not path.exists(): raise HTTPException(410,'The attached print file is missing')
    return FileResponse(path,filename=row['toolpath_original_name'] or path.name,media_type='application/octet-stream')

@app.delete("/api/jobs/{item_id}", dependencies=[Depends(auth)])
def delete_job(item_id: str):
    with db() as conn:
        row=conn.execute("SELECT * FROM jobs WHERE id=?",(item_id,)).fetchone()
        if not row: return {'ok':True}
        if row['stock_deducted_material_id'] and float(row['stock_deducted_amount'] or 0): add_material_transaction(conn,row['stock_deducted_material_id'],float(row['stock_deducted_amount']),'Print stock correction','Restored because print record was deleted',item_id)
        counted={str(k):max(0,int(v or 0)) for k,v in as_json_dict(row['counted_models_json']).items() if k}
        if not counted and row['counted_model_id']: counted={str(row['counted_model_id']):1}
        for model_id,quantity in counted.items(): conn.execute("UPDATE models SET print_count=MAX(0,print_count-?),updated_at=? WHERE id=?",(quantity,now_iso(),model_id))
        photo=row['result_photo'];toolpath=row['toolpath_file'];conn.execute("DELETE FROM jobs WHERE id=?",(item_id,))
    if photo: (RESULT_DIR/photo).unlink(missing_ok=True)
    if toolpath: (TOOLPATH_DIR/toolpath).unlink(missing_ok=True)
    return {'ok':True}

@app.get("/api/export/print-history.csv", dependencies=[Depends(auth)])
def export_print_history():
    rows=jobs();out=io.StringIO();w=csv.writer(out);w.writerow(['Job','Status','Models','Printer','Material','Inventory code','Rating','Duration minutes','Material used','Unit','Material cost','Completed','Failure','Notes'])
    for j in rows: w.writerow([j['name'],j['status'],'; '.join(f"{item['title']} x{item['quantity']}" for item in j.get('models') or []),j.get('printer_name',''),j.get('material_name',''),j.get('material_inventory_code',''),j.get('result_rating',''),j.get('duration_minutes',''),j.get('material_used',''),j.get('material_unit',''),j.get('material_cost',''),j.get('completed_at',''),'; '.join(j.get('failure_tags') or []),j.get('notes','')])
    return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="layervault-print-history.csv"'})

@app.get("/api/export/materials.csv", dependencies=[Depends(auth)])
def export_materials():
    rows=materials();out=io.StringIO();w=csv.writer(out);w.writerow(['Inventory code','Name','Kind','Material','Brand','Colour','Initial','Remaining','Unit','Status','Batch','Location','Purchase price','Remaining value'])
    for m in rows: w.writerow([m['inventory_code'],m['name'],m['kind'],m['material'],m['brand'],m['color'],m['initial_amount'],m['remaining_amount'],m['unit'],m['stock_status'],m['batch_lot'],m['location'],m.get('purchase_price',''),m.get('remaining_value','')])
    return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="layervault-material-inventory.csv"'})

BACKUP_SCOPE_LABELS = {
    "database": "Database & configuration",
    "devices": "Printers & profiles",
    "materials": "Materials & inventory",
    "models": "Models & model files",
    "projects": "Projects & Workshop designs",
    "print_logs": "Print history & result photos",
}
DEFAULT_BACKUP_SCOPES = list(BACKUP_SCOPE_LABELS)
_backup_lock = threading.Lock()
_backup_schedule_lock = threading.Lock()
_backup_scheduler_stop = threading.Event()
_backup_scheduler_thread: threading.Thread | None = None


def _backup_scopes(value: Any) -> list[str]:
    requested = value if isinstance(value, list) else DEFAULT_BACKUP_SCOPES
    scopes = [scope for scope in DEFAULT_BACKUP_SCOPES if scope in requested]
    if not scopes:
        raise HTTPException(422, "Select at least one backup category")
    return scopes


def _json_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"').fetchall()]


def _archive_directory(archive: zipfile.ZipFile, source: Path, prefix: str) -> int:
    count = 0
    if not source.exists():
        return count
    for path in sorted(source.rglob("*")):
        if path.is_file():
            archive.write(path, f"{prefix}/{path.relative_to(source).as_posix()}")
            count += 1
    return count


def _backup_run_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    result = dict(row)
    result["scopes"] = json.loads(result.pop("scopes_json") or "[]")
    result["download_url"] = f"/api/settings/backups/{result['id']}/download"
    return result


def _schedule_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    result = dict(row)
    result["scopes"] = json.loads(result.pop("scopes_json") or "[]")
    result["enabled"] = bool(result["enabled"])
    return result


def _create_backup(scopes: list[str], reason: str = "manual", schedule_id: str | None = None) -> dict[str, Any]:
    scopes = _backup_scopes(scopes)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    run_id = str(uuid.uuid4())
    suffix = run_id.split("-")[0]
    file_name = f"layervault-{stamp}-{suffix}.zip"
    destination = BACKUP_DIR / file_name
    snapshot = BACKUP_DIR / f".snapshot-{run_id}.db"
    created_at = now_iso()
    manifest: dict[str, Any] = {
        "format": "LayerVault backup",
        "format_version": 1,
        "app_version": app.version,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "created_at": created_at,
        "reason": reason,
        "schedule_id": schedule_id,
        "scopes": scopes,
        "scope_labels": {scope: BACKUP_SCOPE_LABELS[scope] for scope in scopes},
        "asset_files": {},
    }
    table_groups = {
        "devices": ["printers", "profiles"],
        "materials": ["materials", "material_transactions"],
        "models": ["models", "health_reports", "manufacturing_reports", "collections", "collection_models"],
        "projects": ["projects", "project_models", "workshop_designs"],
        "print_logs": ["jobs"],
    }
    with _backup_lock:
        try:
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                if "database" in scopes:
                    with closing(sqlite3.connect(DB_PATH)) as source, closing(sqlite3.connect(snapshot)) as target:
                        source.backup(target)
                    archive.write(snapshot, "database/layervault.db")
                    archive.writestr("configuration/workspace.json", json.dumps({
                        "app_version": app.version,
                        "schema_version": CURRENT_SCHEMA_VERSION,
                        "local_first": True,
                    }, indent=2))
                with db() as conn:
                    for scope, tables in table_groups.items():
                        if scope not in scopes:
                            continue
                        for table in tables:
                            archive.writestr(
                                f"exports/{scope}/{table}.json",
                                json.dumps(_json_rows(conn, table), indent=2, ensure_ascii=False),
                            )
                if "models" in scopes:
                    manifest["asset_files"]["models"] = _archive_directory(archive, FILES_DIR, "files/models")
                if "projects" in scopes:
                    manifest["asset_files"]["sketchforge_projects"] = _archive_directory(archive, SKETCHFORGE_PROJECTS_DIR, "files/sketchforge-projects")
                if "print_logs" in scopes:
                    manifest["asset_files"]["result_photos"] = _archive_directory(archive, RESULT_DIR, "files/print-results")
                    manifest["asset_files"]["job_files"] = _archive_directory(archive, TOOLPATH_DIR, "files/job-files")
                if "devices" in scopes or "materials" in scopes:
                    manifest["asset_files"]["custom_images"] = _archive_directory(archive, CUSTOM_IMAGE_DIR, "files/custom-images")
                archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            size_bytes = destination.stat().st_size
            with db() as conn:
                conn.execute(
                    "INSERT INTO backup_runs(id,file_name,reason,schedule_id,scopes_json,size_bytes,created_at) VALUES(?,?,?,?,?,?,?)",
                    (run_id, file_name, reason, schedule_id, json.dumps(scopes), size_bytes, created_at),
                )
                row = conn.execute("SELECT * FROM backup_runs WHERE id=?", (run_id,)).fetchone()
            return _backup_run_dict(row) or {}
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            snapshot.unlink(missing_ok=True)


def _schedule_values(payload: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    source = {**(current or {}), **(payload or {})}
    frequency = str(source.get("frequency") or "weekly").lower()
    if frequency not in {"daily", "weekly", "monthly"}:
        raise HTTPException(422, "Backup frequency must be daily, weekly or monthly")
    time_local = str(source.get("time_local") or "02:00")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_local):
        raise HTTPException(422, "Backup time must use HH:MM")
    return {
        "name": str(source.get("name") or "Automatic backup").strip()[:80] or "Automatic backup",
        "frequency": frequency,
        "time_local": time_local,
        "weekday": max(0, min(6, int(source.get("weekday", 6)))),
        "month_day": max(1, min(28, int(source.get("month_day", 1)))),
        "scopes": _backup_scopes(source.get("scopes")),
        "keep_count": max(1, min(100, int(source.get("keep_count", 10)))),
        "enabled": bool(source.get("enabled", True)),
    }


def _next_schedule_at(values: dict[str, Any], after: datetime | None = None) -> str:
    now = after or datetime.now().astimezone()
    hour, minute = (int(part) for part in values["time_local"].split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if values["frequency"] == "daily":
        if candidate <= now:
            candidate += timedelta(days=1)
    elif values["frequency"] == "weekly":
        days = (values["weekday"] - candidate.weekday()) % 7
        candidate += timedelta(days=days)
        if candidate <= now:
            candidate += timedelta(days=7)
    else:
        year, month = now.year, now.month
        day = min(values["month_day"], calendar.monthrange(year, month)[1])
        candidate = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            month += 1
            if month == 13:
                year, month = year + 1, 1
            day = min(values["month_day"], calendar.monthrange(year, month)[1])
            candidate = candidate.replace(year=year, month=month, day=day)
    return candidate.isoformat()


def _prune_schedule_backups(schedule_id: str, keep_count: int) -> None:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM backup_runs WHERE schedule_id=? ORDER BY created_at DESC", (schedule_id,)
        ).fetchall()
        for row in rows[keep_count:]:
            (BACKUP_DIR / row["file_name"]).unlink(missing_ok=True)
            conn.execute("DELETE FROM backup_runs WHERE id=?", (row["id"],))


def _run_due_schedules() -> int:
    with _backup_schedule_lock:
        local_now = datetime.now().astimezone()
        with db() as conn:
            due = conn.execute(
                "SELECT * FROM backup_schedules WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at<=? ORDER BY next_run_at",
                (local_now.isoformat(),),
            ).fetchall()
        completed = 0
        for row in due:
            schedule = _schedule_dict(row) or {}
            succeeded = False
            try:
                _create_backup(schedule["scopes"], "scheduled", schedule["id"])
                completed += 1
                succeeded = True
                last_run = now_iso()
            except Exception:
                last_run = row["last_run_at"]
            values = {
                "frequency": schedule["frequency"], "time_local": schedule["time_local"],
                "weekday": schedule["weekday"], "month_day": schedule["month_day"],
            }
            with db() as conn:
                conn.execute(
                    "UPDATE backup_schedules SET last_run_at=?,next_run_at=?,updated_at=? WHERE id=?",
                    (last_run, _next_schedule_at(values, local_now + timedelta(seconds=1)), now_iso(), schedule["id"]),
                )
            if succeeded:
                _prune_schedule_backups(schedule["id"], schedule["keep_count"])
        return completed


def _backup_scheduler_loop() -> None:
    while not _backup_scheduler_stop.wait(30):
        try:
            _run_due_schedules()
        except Exception:
            pass


@app.on_event("startup")
def start_backup_scheduler() -> None:
    global _backup_scheduler_thread
    if _backup_scheduler_thread and _backup_scheduler_thread.is_alive():
        return
    _backup_scheduler_stop.clear()
    _backup_scheduler_thread = threading.Thread(target=_backup_scheduler_loop, name="layervault-backups", daemon=True)
    _backup_scheduler_thread.start()


@app.on_event("shutdown")
def stop_backup_scheduler() -> None:
    _backup_scheduler_stop.set()


def _storage_location(kind: str, path: Path, host_env: str) -> dict[str, Any]:
    """Describe a Docker-backed storage location without exposing arbitrary files."""
    try:
        usage = shutil.disk_usage(path)
        free_bytes = usage.free
    except OSError:
        free_bytes = None
    return {
        "kind": kind,
        "container_path": str(path),
        "host_path": os.getenv(host_env, "").strip(),
        "exists": path.exists(),
        "writable": path.is_dir() and os.access(path, os.W_OK),
        "free_bytes": free_bytes,
    }


@app.get("/api/settings/backups", dependencies=[Depends(auth)])
def backup_settings():
    _run_due_schedules()
    with db() as conn:
        schedules = [_schedule_dict(row) for row in conn.execute("SELECT * FROM backup_schedules ORDER BY created_at").fetchall()]
        backups = [_backup_run_dict(row) for row in conn.execute("SELECT * FROM backup_runs ORDER BY created_at DESC LIMIT 50").fetchall()]
    return {
        "scopes": [{"id": key, "label": value} for key, value in BACKUP_SCOPE_LABELS.items()],
        "schedules": schedules,
        "backups": backups,
        "storage_bytes": sum((BACKUP_DIR / item["file_name"]).stat().st_size for item in backups if (BACKUP_DIR / item["file_name"]).exists()),
        "storage": {
            "workspace": _storage_location("workspace", DATA_DIR, "LAYERVAULT_DATA_PATH"),
            "database": _storage_location("database", DATABASE_DIR, "LAYERVAULT_DATABASE_PATH"),
            "models": _storage_location("models", FILES_DIR, "LAYERVAULT_MODELS_PATH"),
            "backups": _storage_location("backups", BACKUP_DIR, "LAYERVAULT_BACKUPS_PATH"),
        },
    }


@app.post("/api/settings/backups/run", dependencies=[Depends(auth)])
def run_backup(payload: dict[str, Any] | None = None):
    return _create_backup(_backup_scopes((payload or {}).get("scopes")), "manual")


@app.get("/api/settings/backups/{backup_id}/download", dependencies=[Depends(auth)])
def download_backup(backup_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM backup_runs WHERE id=?", (backup_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Backup not found")
    path = BACKUP_DIR / row["file_name"]
    if not path.exists():
        raise HTTPException(410, "Backup file is missing")
    return FileResponse(path, filename=row["file_name"], media_type="application/zip")


@app.delete("/api/settings/backups/{backup_id}", dependencies=[Depends(auth)])
def delete_backup(backup_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM backup_runs WHERE id=?", (backup_id,)).fetchone()
        if not row:
            return {"ok": True}
        conn.execute("DELETE FROM backup_runs WHERE id=?", (backup_id,))
    (BACKUP_DIR / row["file_name"]).unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/settings/backup-schedules", dependencies=[Depends(auth)])
def create_backup_schedule(payload: dict[str, Any]):
    values = _schedule_values(payload)
    item_id, stamp = str(uuid.uuid4()), now_iso()
    next_run = _next_schedule_at(values) if values["enabled"] else None
    with db() as conn:
        conn.execute(
            "INSERT INTO backup_schedules(id,name,frequency,time_local,weekday,month_day,scopes_json,keep_count,enabled,last_run_at,next_run_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, values["name"], values["frequency"], values["time_local"], values["weekday"], values["month_day"], json.dumps(values["scopes"]), values["keep_count"], int(values["enabled"]), None, next_run, stamp, stamp),
        )
        row = conn.execute("SELECT * FROM backup_schedules WHERE id=?", (item_id,)).fetchone()
    return _schedule_dict(row)


@app.patch("/api/settings/backup-schedules/{schedule_id}", dependencies=[Depends(auth)])
def update_backup_schedule(schedule_id: str, payload: dict[str, Any]):
    with db() as conn:
        row = conn.execute("SELECT * FROM backup_schedules WHERE id=?", (schedule_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Backup schedule not found")
        current = _schedule_dict(row) or {}
        values = _schedule_values(payload, current)
        next_run = _next_schedule_at(values) if values["enabled"] else None
        conn.execute(
            "UPDATE backup_schedules SET name=?,frequency=?,time_local=?,weekday=?,month_day=?,scopes_json=?,keep_count=?,enabled=?,next_run_at=?,updated_at=? WHERE id=?",
            (values["name"], values["frequency"], values["time_local"], values["weekday"], values["month_day"], json.dumps(values["scopes"]), values["keep_count"], int(values["enabled"]), next_run, now_iso(), schedule_id),
        )
        updated = conn.execute("SELECT * FROM backup_schedules WHERE id=?", (schedule_id,)).fetchone()
    return _schedule_dict(updated)


@app.delete("/api/settings/backup-schedules/{schedule_id}", dependencies=[Depends(auth)])
def delete_backup_schedule(schedule_id: str):
    with db() as conn:
        conn.execute("DELETE FROM backup_schedules WHERE id=?", (schedule_id,))
    return {"ok": True}


@app.post("/api/backup", dependencies=[Depends(auth)])
def backup():
    """Compatibility endpoint retained for older clients; new UI lives in Settings."""
    result = _create_backup(DEFAULT_BACKUP_SCOPES, "manual")
    return {"ok": True, "file": result["file_name"], "id": result["id"]}


@app.exception_handler(sqlite3.IntegrityError)
def db_integrity_error(request: Request, exc: sqlite3.IntegrityError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


if os.getenv("AUTO_IMPORT", "").lower() in {"1","true","yes","on"}:
    try:
        scan_import_folder()
    except Exception:
        pass
