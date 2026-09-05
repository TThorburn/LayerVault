from pathlib import Path
import os, sqlite3, sys, tempfile
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='layervault-pass9-fresh-')
from app.main import DB_PATH, app
assert app.version=='0.3.29'
conn=sqlite3.connect(DB_PATH)
tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert {'models','projects','materials','printers','profiles','collections','jobs','job_models','material_transactions','custom_image_assets','custom_image_bindings','health_reports','manufacturing_reports','workshop_designs','backup_schedules','backup_runs'} <= tables
mat_cols={r[1] for r in conn.execute('PRAGMA table_info(materials)')}
job_cols={r[1] for r in conn.execute('PRAGMA table_info(jobs)')}
project_model_cols={r[1] for r in conn.execute('PRAGMA table_info(project_models)')}
prn_cols={r[1] for r in conn.execute('PRAGMA table_info(printers)')}
model_cols={r[1] for r in conn.execute('PRAGMA table_info(models)')}
collection_cols={r[1] for r in conn.execute('PRAGMA table_info(collections)')}
assert {'inventory_code','purchase_price','batch_lot','stock_status','source_provider','source_key','source_snapshot','source_image_url','specs','density_g_cm3','diameter_mm','gtin','product_url','custom_image_asset_id'} <= mat_cols
profile_cols={r[1] for r in conn.execute('PRAGMA table_info(profiles)')}
assert {'profile_origin','source_provider','source_key','source_snapshot'} <= profile_cols
assert {'settings_snapshot','result_metrics','failure_tags','stock_deducted_amount','material_cost','toolpath_file','toolpath_original_name','toolpath_size_bytes','toolpath_metadata','counted_models_json'} <= job_cols
assert {'urgency','importance'} <= project_model_cols
assert {'inventory_code','serial_number','location','printer_status','firmware_version','last_service_at','nozzle_options','resolution_x','resolution_y','xy_resolution_x_um','xy_resolution_y_um','screen_width_mm','screen_height_mm','capabilities','source_provider','source_key','source_snapshot','source_image_url','custom_image_asset_id'} <= prn_cols
assert 'thumbnail_view' in model_cols
assert 'parent_id' in collection_cols
conn.close()
with sqlite3.connect(DB_PATH) as conn:
    model_indexes={r[1] for r in conn.execute("PRAGMA index_list('models')").fetchall()}
    assert {'idx_models_title','idx_models_added_at','idx_models_category','idx_models_status'}.issubset(model_indexes)
print('LayerVault v0.3.29 fresh-install schema test: PASS')
