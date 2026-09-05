"""Regression: an older LayerVault alpha DB must not crash current startup.

This fixture deliberately resembles an early schema: collections has no parent_id,
materials/printers have no inventory/source fields, and jobs has no Print Lab snapshot
columns. Importing app.main triggers init_db() and must reconcile it before indexes.
"""
import os
import sqlite3
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

root = Path(tempfile.mkdtemp(prefix="layervault-schema-drift-"))
os.environ["DATA_DIR"] = str(root)
db_path = root / "layervault.db"
conn = sqlite3.connect(db_path)
conn.executescript("""
CREATE TABLE models (
 id TEXT PRIMARY KEY,title TEXT NOT NULL,original_filename TEXT NOT NULL,stored_filename TEXT NOT NULL,
 extension TEXT NOT NULL,size_bytes INTEGER NOT NULL DEFAULT 0,sha256 TEXT NOT NULL,category TEXT NOT NULL DEFAULT 'Unsorted',
 creator TEXT NOT NULL DEFAULT '',source_url TEXT NOT NULL DEFAULT '',license TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',
 tags TEXT NOT NULL DEFAULT '[]',favorite INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'Ready',print_count INTEGER NOT NULL DEFAULT 0,
 triangles INTEGER,width_mm REAL,depth_mm REAL,height_mm REAL,added_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE TABLE projects (id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'Planning',tags TEXT NOT NULL DEFAULT '[]',due_date TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE project_models (project_id TEXT NOT NULL,model_id TEXT NOT NULL,quantity INTEGER NOT NULL DEFAULT 1,variant TEXT NOT NULL DEFAULT '',PRIMARY KEY(project_id,model_id));
CREATE TABLE materials (id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'Filament',material TEXT NOT NULL DEFAULT 'PLA',brand TEXT NOT NULL DEFAULT '',color TEXT NOT NULL DEFAULT '',color_hex TEXT NOT NULL DEFAULT '#808080',initial_amount REAL NOT NULL DEFAULT 1000,remaining_amount REAL NOT NULL DEFAULT 1000,unit TEXT NOT NULL DEFAULT 'g',location TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',opened_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE printers (id TEXT PRIMARY KEY,name TEXT NOT NULL,technology TEXT NOT NULL DEFAULT 'FDM',manufacturer TEXT NOT NULL DEFAULT '',model TEXT NOT NULL DEFAULT '',build_x REAL,build_y REAL,build_z REAL,nozzle_mm REAL,notes TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE profiles (id TEXT PRIMARY KEY,name TEXT NOT NULL,technology TEXT NOT NULL DEFAULT 'FDM',printer_id TEXT,material TEXT NOT NULL DEFAULT '',layer_height REAL,settings TEXT NOT NULL DEFAULT '{}',notes TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE collections (id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',kind TEXT NOT NULL DEFAULT 'manual',filter_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE collection_models (collection_id TEXT NOT NULL,model_id TEXT NOT NULL,added_at TEXT NOT NULL,PRIMARY KEY(collection_id,model_id));
CREATE TABLE jobs (id TEXT PRIMARY KEY,name TEXT NOT NULL,project_id TEXT,model_id TEXT,printer_id TEXT,material_id TEXT,profile_id TEXT,status TEXT NOT NULL DEFAULT 'Queued',duration_minutes INTEGER,material_used REAL,result_rating INTEGER,notes TEXT NOT NULL DEFAULT '',started_at TEXT,completed_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
INSERT INTO models VALUES ('m1','Old model','old.stl','old.stl','.stl',10,'sha-old','Unsorted','','','','','[]',0,'Ready',0,NULL,NULL,NULL,NULL,'2026-01-01','2026-01-01');
INSERT INTO materials VALUES ('mat1','Old PLA','Filament','PLA','Example','Black','#000000',1000,700,'g','Shelf','','2026-01-01','2026-01-01','2026-01-01');
INSERT INTO printers VALUES ('pr1','Old Printer','FDM','Example','Old',220,220,250,0.4,'','2026-01-01','2026-01-01');
INSERT INTO collections VALUES ('c1','Old folder','','manual','{}','2026-01-01','2026-01-01');
""")
conn.commit(); conn.close()

from app.main import DB_PATH, app  # noqa: E402
assert app.version == "0.3.29"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

def cols(table):
    return {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}

assert {'parent_id'} <= cols('collections')
assert {'parent_model_id','root_model_id','thumbnail_view'} <= cols('models')
assert {'inventory_code','source_provider','source_image_url','specs','density_g_cm3','custom_image_asset_id'} <= cols('materials')
assert {'inventory_code','source_provider','resolution_x','resolution_y','source_image_url','custom_image_asset_id'} <= cols('printers')
assert {'profile_origin','source_provider'} <= cols('profiles')
assert {'settings_snapshot','failure_tags','stock_deducted_amount','counted_models_json'} <= cols('jobs')
assert {'toolpath_file','toolpath_original_name','toolpath_size_bytes','toolpath_metadata'} <= cols('jobs')
assert {'urgency','importance'} <= cols('project_models')
assert {'document_json','revision','last_export_model_id'} <= cols('workshop_designs')
assert conn.execute("SELECT inventory_code FROM materials WHERE id='mat1'").fetchone()[0].startswith('LV-MAT-')
assert conn.execute("SELECT inventory_code FROM printers WHERE id='pr1'").fetchone()[0].startswith('LV-PRN-')
assert conn.execute("SELECT root_model_id FROM models WHERE id='m1'").fetchone()[0] == 'm1'
indexes = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
assert 'idx_collections_parent' in indexes
assert 'idx_materials_source' in indexes
assert 'idx_printers_source' in indexes
assert {'custom_image_assets','custom_image_bindings','job_models'} <= {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert conn.execute('PRAGMA user_version').fetchone()[0] == 128
conn.close()
print('LayerVault v0.3.29 schema-drift startup regression: PASS')
