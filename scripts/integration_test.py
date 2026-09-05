from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import io
import os
import tempfile

os.environ['DATA_DIR'] = tempfile.mkdtemp(prefix='layervault-pass9-integration-')

from PIL import Image
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

def stl(seed: int) -> bytes:
    return f'''solid model{seed}\nfacet normal 0 0 1\n outer loop\n  vertex 0 0 0\n  vertex {10 + seed} 0 0\n  vertex 0 {8 + seed} {seed}\n endloop\nendfacet\nendsolid model{seed}\n'''.encode()

def upload(name, seed, category='Unsorted', tags='', creator=''):
    r=c.post('/api/models/upload', files={'file':(name,stl(seed),'application/octet-stream')}, data={'category':category,'tags':tags,'creator':creator})
    assert r.status_code == 200, r.text
    return r.json()

# Core library + lineage remains healthy.
a=upload('Goblin Archer.stl',1,'Miniatures','goblin, fantasy, 28mm','Fantasy Forge')
b=upload('Cable Clip.stl',2,'Functional','clip, repair','Workshop Lab')
m1,m2=a['model'],b['model']
assert a['created'] and b['created']
renamed=c.post('/api/models/upload',files={'file':('cryptic_filename_482.stl',stl(99),'application/octet-stream')},data={'title':'Wheel bracket — left'}).json()
assert renamed['created'] and renamed['model']['title']=='Wheel bracket — left' and renamed['model']['original_filename']=='cryptic_filename_482.stl'
assert c.post('/api/models/upload',files={'file':('Goblin Copy.stl',stl(1),'application/octet-stream')},data={}).json()['created'] is False
thumb=c.get(f"/api/models/{m1['id']}/thumbnail"); assert thumb.status_code==200 and thumb.headers['content-type'].startswith('image/webp') and len(thumb.content)>100
child=c.post(f"/api/models/{m1['id']}/derive",files={'file':('Goblin 32mm.stl',stl(7),'application/octet-stream')},data={'title':'Goblin Archer — 32 mm','version_label':'32 mm','derivation_type':'Scaled'}).json()['model']
assert child['parent_model_id']==m1['id'] and child['root_model_id']==m1['id']

# Cached thumbnail camera: root overrides flow through lineage until a child overrides them.
default_view=c.get(f"/api/models/{m1['id']}/thumbnail-view").json(); assert default_view['effective']['yaw_deg']==22.0 and default_view['local']=={}
custom={'yaw_deg':8,'pitch_deg':24,'zoom':1.08}
assert c.put(f"/api/models/{m1['id']}/thumbnail-view",json=custom).status_code==200
thumb_custom=c.get(f"/api/models/{m1['id']}/thumbnail"); assert thumb_custom.status_code==200 and thumb_custom.content!=thumb.content
inherited=c.get(f"/api/models/{child['id']}/thumbnail-view").json(); assert inherited['inherited'] is True and inherited['effective']['yaw_deg']==8.0
assert c.put(f"/api/models/{child['id']}/thumbnail-view",json={'yaw_deg':-35,'pitch_deg':15,'zoom':1}).status_code==200
c.put(f"/api/models/{m1['id']}/thumbnail-view",json={'yaw_deg':30,'pitch_deg':20,'zoom':1})
child_custom=c.get(f"/api/models/{child['id']}/thumbnail-view").json(); assert child_custom['effective']['yaw_deg']==-35.0 and child_custom['inherited'] is False
reset=c.delete(f"/api/models/{child['id']}/thumbnail-view").json(); assert reset['inherited'] is True and reset['effective']['yaw_deg']==30.0

# Hierarchical library folders + Unfiled view.
root_folder=c.post('/api/collections',json={'name':'D&D','kind':'manual'}).json()
sub_folder=c.post('/api/collections',json={'name':'Fey','kind':'manual','parent_id':root_folder['id']}).json()
smart=c.post('/api/collections',json={'name':'Ready minis','kind':'smart','parent_id':root_folder['id'],'filter':{'category':'Miniatures','status':'Ready'}}).json()
assert sub_folder['parent_id']==root_folder['id'] and smart['parent_id']==root_folder['id']
assert c.post(f"/api/collections/{sub_folder['id']}/models",json={'model_ids':[m1['id']]}).status_code==200
assert any(x['id']==m1['id'] for x in c.get('/api/models',params={'collection_id':sub_folder['id']}).json())
unfiled_ids={x['id'] for x in c.get('/api/models',params={'unfiled':'true'}).json()}; assert m1['id'] not in unfiled_ids and m2['id'] in unfiled_ids
cycle=c.patch(f"/api/collections/{root_folder['id']}",json={'parent_id':sub_folder['id']}); assert cycle.status_code==400

# Project quantities / variants and atomic editor save.
p=c.post('/api/projects',json={'name':'Goblin Warband','status':'Planning'}).json()
first_link=c.post(f"/api/projects/{p['id']}/models/{m1['id']}",json={'quantity':8,'variant':'28 mm archers','urgency':5,'importance':4}).json()['models'][0]
assert first_link['quantity']==8 and first_link['urgency']==5 and first_link['importance']==4 and first_link['priority_score']==9
# The UI now saves metadata + linked model plan in one PATCH so selecting a model and
# pressing the bottom Save project button cannot silently lose the link.
ps=c.patch(f"/api/projects/{p['id']}",json={'name':'Goblin Warband Refined','status':'Ready to print','tags':['campaign'],'models':[{'model_id':m1['id'],'quantity':9,'variant':'archers','urgency':5,'importance':5},{'model_id':m2['id'],'quantity':2,'variant':'clips','urgency':2,'importance':3}]})
assert ps.status_code==200, ps.text
pd=ps.json(); assert pd['name']=='Goblin Warband Refined' and len(pd['models'])==2
assert {x['id']:x['quantity'] for x in pd['models']}=={m1['id']:9,m2['id']:2}
assert [x['id'] for x in pd['models']]==[m1['id'],m2['id']] and pd['models'][0]['priority_score']==10
ps=c.patch(f"/api/projects/{p['id']}",json={'models':[{'model_id':m1['id'],'quantity':4,'variant':'hero set'}]})
assert ps.status_code==200 and len(ps.json()['models'])==1 and ps.json()['models'][0]['variant']=='hero set'
p=ps.json()
# Invalid links fail without partially saving project metadata.
bad=c.patch(f"/api/projects/{p['id']}",json={'name':'Should not persist','models':[{'model_id':'missing-model','quantity':1}]})
assert bad.status_code==404
assert c.get(f"/api/projects/{p['id']}").json()['name']=='Goblin Warband Refined'

# Physical resin bottle inventory with purchasing / batch / cost data.
mat=c.post('/api/materials',json={
    'name':'Elegoo ABS-Like Grey — Bottle 1','kind':'Resin','material':'ABS-Like','brand':'Elegoo','color':'Grey','unit':'ml',
    'initial_amount':1000,'remaining_amount':1000,'purchase_price':30,'supplier':'Printer Shop','batch_lot':'R26-08','location':'Resin cupboard','stock_status':'Open'
}).json()
assert mat['inventory_code'].startswith('LV-MAT-')
assert mat['cost_per_unit']==0.03 and mat['remaining_percent']==100.0 and mat['low_stock'] is False

# Multiple owned printers + detailed inventory fields.
printer=c.post('/api/printers',json={
    'name':'Saturn Workshop','technology':'MSLA / Resin','manufacturer':'Elegoo','model':'Saturn 4 Ultra','serial_number':'SAT-001',
    'location':'Workshop','purchase_price':350,'printer_status':'Active','firmware_version':'1.2.3','build_x':218.88,'build_y':122.88,'build_z':220
}).json()
fdm=c.post('/api/printers',json={'name':'CoreXY Bench','technology':'FDM','manufacturer':'Generic','model':'CoreXY','serial_number':'FDM-001','location':'Workshop','nozzle_mm':0.4}).json()
assert printer['inventory_code'].startswith('LV-PRN-') and fdm['inventory_code'].startswith('LV-PRN-') and printer['inventory_code']!=fdm['inventory_code']
assert len(c.get('/api/printers').json())==2

# Structured Resin and FDM profiles.
resin_profile=c.post('/api/profiles',json={'name':'0.03 Miniatures','technology':'MSLA / Resin','printer_id':printer['id'],'material':'ABS-Like','layer_height':0.03,'settings':{
    'layer_height_mm':0.03,'normal_exposure_s':2.1,'bottom_exposure_s':28,'bottom_layers':5,'lift_distance_mm':7,'lift_speed_mms':2.0,'retract_wait_s':0.8,'post_cure_minutes':3
}}).json()
fdm_profile=c.post('/api/profiles',json={'name':'PLA Quality','technology':'FDM','printer_id':fdm['id'],'material':'PLA','settings':{
    'layer_height_mm':0.2,'nozzle_temp_c':210,'bed_temp_c':60,'print_speed_mms':120,'retraction_distance_mm':0.8,'retraction_speed_mms':35
}}).json()
assert resin_profile['settings']['normal_exposure_s']==2.1 and fdm_profile['settings']['nozzle_temp_c']==210

# Job snapshots inherit profile values but preserve job-specific overrides.
job=c.post('/api/jobs',json={
    'name':'Goblin plate','project_id':p['id'],'model_id':m1['id'],'printer_id':printer['id'],'material_id':mat['id'],'profile_id':resin_profile['id'],
    'technology':'MSLA / Resin','status':'Printing','settings_snapshot':{'normal_exposure_s':2.0,'retract_wait_s':1.0,'resin_temperature_c':24}
}).json()
assert job['settings_snapshot']['bottom_exposure_s']==28
assert job['settings_snapshot']['normal_exposure_s']==2.0
assert job['settings_snapshot']['retract_wait_s']==1.0

# Complete 5-star result: stock deduction, cost, sub-ratings, exact settings and model count.
r=c.patch(f"/api/jobs/{job['id']}",json={
    'status':'Complete','duration_minutes':132,'material_used':42,'result_rating':5,
    'result_metrics':{'quality':5,'reliability':5,'supports':4},'notes':'Crisp detail','completed_at':'2026-08-20T10:00:00+00:00'
})
assert r.status_code==200, r.text
detail=r.json(); assert detail['material_cost']==1.26 and detail['stock_deducted_amount']==42 and detail['result_metrics']['quality']==5
assert c.get(f"/api/materials/{mat['id']}").json()['remaining_amount']==958
assert c.get(f"/api/models/{m1['id']}").json()['print_count']==1

# Correcting usage adjusts only the difference and doesn't double-count prints.
c.patch(f"/api/jobs/{job['id']}",json={'status':'Complete','material_used':50})
assert c.get(f"/api/materials/{mat['id']}").json()['remaining_amount']==950
assert c.get(f"/api/models/{m1['id']}").json()['print_count']==1
assert c.get(f"/api/jobs/{job['id']}").json()['material_cost']==1.5

# Failed attempts consume stock and record structured failure categories.
failed=c.post('/api/jobs',json={
    'name':'Goblin retry','model_id':m1['id'],'printer_id':printer['id'],'material_id':mat['id'],'profile_id':resin_profile['id'],'technology':'MSLA / Resin',
    'status':'Failed','material_used':10,'result_rating':2,'failure_tags':['Support failure','Under-exposure'],'failure_reason':'Bow detached',
    'settings_snapshot':{'normal_exposure_s':1.7,'retract_wait_s':0.2},'completed_at':'2026-08-20T11:00:00+00:00'
}).json()
assert failed['failure_tags']==['Support failure','Under-exposure']
assert c.get(f"/api/materials/{mat['id']}").json()['remaining_amount']==940

# Insights identify the better recipe for the exact model/material/printer combination.
ins=c.get('/api/jobs/insights/recipe',params={'model_id':m1['id'],'material_id':mat['id'],'printer_id':printer['id']}).json()
assert ins['attempts']==2 and ins['success_rate']==50.0 and ins['best']['id']==job['id'] and ins['avg_rating']==3.5

# Material / printer / profile performance metrics.
md=c.get(f"/api/materials/{mat['id']}").json(); assert md['print_attempts']==2 and md['avg_rating']==3.5 and len(md['transactions'])>=3
pd=c.get(f"/api/printers/{printer['id']}").json(); assert pd['print_attempts']==2 and pd['success_rate']==50.0
profiles={x['id']:x for x in c.get('/api/profiles').json()}; assert profiles[resin_profile['id']]['job_count']==2 and profiles[resin_profile['id']]['avg_rating']==3.5

# QR labels and result photos.
qr=c.get(f"/api/materials/{mat['id']}/qr"); assert qr.status_code==200 and qr.headers['content-type'].startswith('image/png') and len(qr.content)>200
img=Image.new('RGB',(24,24),'white');buf=io.BytesIO();img.save(buf,format='PNG')
assert c.post(f"/api/jobs/{job['id']}/photo",files={'file':('result.png',buf.getvalue(),'image/png')}).status_code==200
assert c.get(f"/api/jobs/{job['id']}/photo").status_code==200

# Pass 8 convenience: repeat a successful setup without carrying outcome fields forward.
repeat=c.post(f"/api/jobs/{job['id']}/repeat").json()
assert repeat['status']=='Queued' and repeat['printer_id']==printer['id'] and repeat['material_id']==mat['id']
assert repeat['settings_snapshot']==c.get(f"/api/jobs/{job['id']}").json()['settings_snapshot']
assert repeat['result_rating'] is None and repeat['material_used'] is None

# Low-stock signal + manual transaction ledger.
c.post(f"/api/materials/{mat['id']}/adjust",json={'amount_delta':-760,'kind':'Measured correction','note':'Alpha test low stock'})
low=c.get(f"/api/materials/{mat['id']}").json(); assert low['remaining_amount']==180 and low['low_stock'] is True and low['remaining_percent']==18.0

# Deleting a failed job restores only that job's deducted stock.
assert c.delete(f"/api/jobs/{failed['id']}").status_code==200
assert c.get(f"/api/materials/{mat['id']}").json()['remaining_amount']==190

# CSV exports are present and contain expected columns.
for path in ['/api/export/print-history.csv','/api/export/materials.csv']:
    exp=c.get(path); assert exp.status_code==200 and exp.headers['content-type'].startswith('text/csv') and len(exp.text.splitlines())>=2

assert c.get('/health').json()['version']=='0.3.29'
print('LayerVault v0.3.29 integration test: PASS')
