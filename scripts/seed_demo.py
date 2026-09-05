"""Seed a disposable LayerVault alpha workspace with representative Print Lab data.

Run inside Docker with:
  docker compose exec layervault python scripts/seed_demo.py

Use only with test data: this deliberately adds sample records to the active DATA_DIR.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app

c=TestClient(app)

def ok(r):
    if r.status_code >= 400: raise RuntimeError(r.text)
    return r.json()

stl=b'''solid demo\nfacet normal 0 0 1\n outer loop\n  vertex 0 0 0\n  vertex 25 0 0\n  vertex 0 32 5\n endloop\nendfacet\nendsolid demo\n'''
model=ok(c.post('/api/models/upload',files={'file':('Demo Knight.stl',stl,'application/octet-stream')},data={'category':'Miniatures','tags':'demo, knight, 32mm'}))['model']
resin=ok(c.post('/api/materials',json={'name':'Demo Grey Resin — Bottle 1','kind':'Resin','material':'ABS-Like','brand':'Demo Resin','color':'Grey','unit':'ml','initial_amount':1000,'remaining_amount':1000,'purchase_price':28.50,'batch_lot':'DEMO-R1','location':'Demo shelf'}))
pla=ok(c.post('/api/materials',json={'name':'Demo PLA — Spool 1','kind':'Filament','material':'PLA','brand':'Demo Filament','color':'Blue','unit':'g','initial_amount':1000,'remaining_amount':1000,'purchase_price':18.00,'batch_lot':'DEMO-F1','location':'Demo shelf'}))
resin_printer=ok(c.post('/api/printers',json={'name':'Demo Resin Printer','technology':'MSLA / Resin','manufacturer':'Demo','model':'MSLA 10','serial_number':'DEMO-RP-001','location':'Workshop','printer_status':'Active','build_x':220,'build_y':125,'build_z':250,'resolution_x':11520,'resolution_y':5120,'xy_resolution_x_um':19.1,'xy_resolution_y_um':24.4,'screen_width_mm':220,'screen_height_mm':125}))
fdm_printer=ok(c.post('/api/printers',json={'name':'Demo FDM Printer','technology':'FDM','manufacturer':'Demo','model':'CoreXY','serial_number':'DEMO-FP-001','location':'Workshop','printer_status':'Active','build_x':256,'build_y':256,'build_z':256,'nozzle_mm':0.4}))
profile=ok(c.post('/api/profiles',json={'name':'Demo 0.03 Miniatures','technology':'MSLA / Resin','printer_id':resin_printer['id'],'material':'ABS-Like','settings':{'layer_height_mm':0.03,'normal_exposure_s':2.1,'bottom_exposure_s':28,'bottom_layers':5,'lift_distance_mm':7,'lift_speed_mms':2.0,'retract_wait_s':0.8,'post_cure_minutes':3}}))
job=ok(c.post('/api/jobs',json={'name':'Demo Knight — successful print','model_id':model['id'],'printer_id':resin_printer['id'],'material_id':resin['id'],'profile_id':profile['id'],'technology':'MSLA / Resin','status':'Complete','duration_minutes':145,'material_used':46,'result_rating':5,'result_metrics':{'quality':5,'reliability':5,'supports':4},'settings_snapshot':{'normal_exposure_s':2.05,'resin_temperature_c':24},'notes':'Demo five-star recipe result'}))
ok(c.post('/api/jobs',json={'name':'Demo Knight — exposure test','model_id':model['id'],'printer_id':resin_printer['id'],'material_id':resin['id'],'profile_id':profile['id'],'technology':'MSLA / Resin','status':'Failed','duration_minutes':38,'material_used':12,'result_rating':2,'failure_tags':['Under-exposure','Support failure'],'failure_reason':'Demo failed recipe for comparison','settings_snapshot':{'normal_exposure_s':1.7,'retract_wait_s':0.2}}))
print('LayerVault demo data added.')
print(f"Model: {model['title']}")
print(f"Materials: {resin['inventory_code']}, {pla['inventory_code']}")
print(f"Printers: {resin_printer['inventory_code']}, {fdm_printer['inventory_code']}")
print(f"Successful job: {job['name']}")
