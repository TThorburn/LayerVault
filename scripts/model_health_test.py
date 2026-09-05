from pathlib import Path
import os, struct, sys, tempfile
root=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(root))
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='layervault-health-')
from fastapi.testclient import TestClient
from app.main import app


def binary_stl(tris):
    out=bytearray(b'LayerVault test'.ljust(80,b'\0')); out += struct.pack('<I',len(tris))
    for tri in tris:
        a,b,c=tri
        # normals are ignored by the health engine; write zero normal
        vals=[0.0,0.0,0.0,*a,*b,*c]
        out += struct.pack('<12fH',*vals,0)
    return bytes(out)

v=[(0.,0.,0.),(10.,0.,0.),(10.,10.,0.),(0.,10.,0.),(0.,0.,10.),(10.,0.,10.),(10.,10.,10.),(0.,10.,10.)]
faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
tris=[tuple(v[i] for i in f) for f in faces]
client=TestClient(app)
assert client.get('/health').json()['version']=='0.3.29'

# healthy cube
r=client.post('/api/models/upload',files={'file':('cube.stl',binary_stl(tris),'model/stl')},data={'title':'Healthy Cube'})
assert r.status_code==200,r.text
cube=r.json()['model']
health=client.get(f"/api/models/{cube['id']}/health").json()
assert health['analyzable'] is True
assert health['grade']=='Healthy',health
assert health['score']==100
assert health['metrics']['watertight'] is True
assert health['metrics']['boundary_edges']==0
assert round(health['metrics']['volume_mm3'])==1000
# cached summary appears in library
listed=client.get('/api/models').json(); cm=next(x for x in listed if x['id']==cube['id'])
assert cm['health']['grade']=='Healthy' and cm['health']['score']==100

# printer-fit is calculated separately from the cached geometry report
pr=client.post('/api/printers',json={'name':'Tiny Printer','technology':'FDM','build_x':8,'build_y':8,'build_z':8,'nozzle_mm':0.4}).json()
fit=client.get(f"/api/models/{cube['id']}/health",params={'printer_id':pr['id']}).json()['printer_fit']
assert fit['available'] is True and fit['fits_current_orientation'] is False and fit['fits_with_axis_rotation'] is False
pr2=client.post('/api/printers',json={'name':'Big Printer','technology':'Resin','build_x':20,'build_y':20,'build_z':25,'resolution_x':1000,'resolution_y':1000,'xy_resolution_x_um':20,'xy_resolution_y_um':20}).json()
fit2=client.get(f"/api/models/{cube['id']}/health",params={'printer_id':pr2['id']}).json()['printer_fit']
assert fit2['fits_current_orientation'] is True

# one missing cube triangle -> open 3-edge boundary, Safe Repair should create a healthy child version
broken_tris=tris[:-1]
r=client.post('/api/models/upload',files={'file':('broken.stl',binary_stl(broken_tris),'model/stl')},data={'title':'Broken Cube'})
assert r.status_code==200,r.text
broken=r.json()['model']
bh=client.get(f"/api/models/{broken['id']}/health").json()
assert bh['grade']=='Review' and bh['metrics']['boundary_edges']==3,bh
assert any(i['code']=='open_edges' and i['repairable'] for i in bh['issues'])
repair=client.post(f"/api/models/{broken['id']}/health/repair")
assert repair.status_code==200,repair.text
payload=repair.json(); assert payload['created'] is True,payload
child=payload['model']; assert child['parent_model_id']==broken['id']; assert child['derivation_type']=='Repaired'; assert child['version_label']=='Safe Repair'
assert payload['after']['grade']=='Healthy' and payload['after']['metrics']['watertight'] is True
lineage=client.get(f"/api/models/{child['id']}/lineage").json()
assert lineage['root_id']==broken['id'] and len(lineage['family'])==2
# original is still broken and its stored file remains distinct
bh2=client.get(f"/api/models/{broken['id']}/health").json(); assert bh2['metrics']['boundary_edges']==3
assert child['sha256'] != broken['sha256']

# Duplicate triangles must be removed from the persisted repaired STL. Re-analysis
# with refresh=True deliberately bypasses the report inserted by the repair route.
duplicate_tris=tris+[tris[0],tuple(reversed(tris[1])),tris[2],tuple(reversed(tris[3])),tris[4]]
r=client.post('/api/models/upload',files={'file':('duplicates.stl',binary_stl(duplicate_tris),'model/stl')},data={'title':'Duplicate Cube'})
assert r.status_code==200,r.text
duplicate_model=r.json()['model']
dh=client.get(f"/api/models/{duplicate_model['id']}/health",params={'refresh':'true'}).json()
assert dh['metrics']['duplicate_faces']==5,dh
duplicate_repair=client.post(f"/api/models/{duplicate_model['id']}/health/repair")
assert duplicate_repair.status_code==200,duplicate_repair.text
dp=duplicate_repair.json(); assert dp['created'] is True,dp
assert dp['verified'] is True and dp['reused'] is False,dp
assert any('Removed 5 duplicate triangle(s)' in action for action in dp['actions']),dp
repaired_id=dp['model']['id']
reanalyzed=client.get(f"/api/models/{repaired_id}/health",params={'refresh':'true'}).json()
assert reanalyzed['metrics']['duplicate_faces']==0,reanalyzed
assert not any(i['code']=='duplicate' for i in reanalyzed['issues']),reanalyzed

# Repeating Safe Repair on the original must open/reuse the already verified
# clean child instead of leaving the user on the five-duplicate source model.
repeat=client.post(f"/api/models/{duplicate_model['id']}/health/repair")
assert repeat.status_code==200,repeat.text
rp=repeat.json(); assert rp['created'] is False and rp['reused'] is True and rp['verified'] is True,rp
assert rp['model']['id']==repaired_id and rp['after']['metrics']['duplicate_faces']==0,rp

# Exact Bluebell topology: a real closed shell plus five edge-isolated,
# reverse-wound coincident triangle pairs. Four pairs are disconnected; one
# touches the main shell at one vertex, so the report has five components.
bluebell_like=list(tris)
sheet_triangles=[]
for sheet in range(4):
    x=40.0+sheet*10.0
    triangle=((x,0.,0.),(x+2.,0.,0.),(x,2.,0.))
    sheet_triangles.extend((triangle,tuple(reversed(triangle))))
attached=((0.,0.,0.),(-2.,-1.,0.),(-1.,-2.,0.))
sheet_triangles.extend((attached,tuple(reversed(attached))))
bluebell_like.extend(sheet_triangles)
r=client.post('/api/models/upload',files={'file':('bluebell-sheet-pairs.stl',binary_stl(bluebell_like),'model/stl')},data={'title':'Bluebell Sheet-Pair Topology'})
bluebell_like_id=r.json()['model']['id']
bluebell_like_before=client.get(f"/api/models/{bluebell_like_id}/health",params={'refresh':'true'}).json()
assert bluebell_like_before['score']==95 and bluebell_like_before['metrics']['duplicate_faces']==5,bluebell_like_before
assert bluebell_like_before['metrics']['isolated_duplicate_sheet_groups']==5 and bluebell_like_before['metrics']['isolated_duplicate_sheet_faces']==10,bluebell_like_before
assert bluebell_like_before['metrics']['boundary_edges']==0 and bluebell_like_before['metrics']['watertight'] is True,bluebell_like_before
assert bluebell_like_before['metrics']['components']==5,bluebell_like_before
assert any(i['title']=='Zero-thickness duplicate sheets' for i in bluebell_like_before['issues']),bluebell_like_before
bluebell_like_repair=client.post(f"/api/models/{bluebell_like_id}/health/repair")
assert bluebell_like_repair.status_code==200,bluebell_like_repair.text
br=bluebell_like_repair.json(); assert br['verified'] is True and (br['created'] is True or br['reused'] is True),br
assert any('Removed 10 faces forming 5 isolated two-sided duplicate sheet(s)' in action for action in br['actions']),br
bluebell_like_after=client.get(f"/api/models/{br['model']['id']}/health",params={'refresh':'true'}).json()
assert bluebell_like_after['score']==100 and bluebell_like_after['metrics']['duplicate_faces']==0,bluebell_like_after
assert bluebell_like_after['metrics']['boundary_edges']==0 and bluebell_like_after['metrics']['watertight'] is True,bluebell_like_after
assert bluebell_like_after['metrics']['components']==1,bluebell_like_after

# Regression for the Bluebell false-positive: these distinct triangles have
# identical independently sorted X/Y/Z value sets, but are not duplicate faces.
collision_tris=[((0.,0.,0.),(1.,1.,0.),(2.,0.,0.)),((0.,1.,0.),(1.,0.,0.),(2.,0.,0.))]
r=client.post('/api/models/upload',files={'file':('coordinate-collision.stl',binary_stl(collision_tris),'model/stl')},data={'title':'Distinct Coordinate Sets'})
collision_id=r.json()['model']['id']
collision_health=client.get(f"/api/models/{collision_id}/health",params={'refresh':'true'}).json()
assert collision_health['metrics']['duplicate_faces']==0,collision_health

# Repair the exact topology produced by the old false-positive bug: five
# disconnected closed cubes, each missing one triangle -> 15 boundary edges.
damaged=[]
for shell in range(5):
    offset=float(shell*20)
    shell_vertices=[(x+offset,y,z) for x,y,z in v]
    shell_tris=[tuple(shell_vertices[i] for i in f) for f in faces]
    damaged.extend(shell_tris[:-1])
r=client.post('/api/models/upload',files={'file':('five-shells-15-open-edges.stl',binary_stl(damaged),'model/stl')},data={'title':'Five Damaged Shells'})
damaged_id=r.json()['model']['id']
damaged_before=client.get(f"/api/models/{damaged_id}/health",params={'refresh':'true'}).json()
assert damaged_before['score']==75 and damaged_before['metrics']['boundary_edges']==15 and damaged_before['metrics']['components']==5,damaged_before
damaged_repair=client.post(f"/api/models/{damaged_id}/health/repair")
assert damaged_repair.status_code==200,damaged_repair.text
dr=damaged_repair.json(); assert dr['created'] is True and dr['verified'] is True,dr
damaged_after=client.get(f"/api/models/{dr['model']['id']}/health",params={'refresh':'true'}).json()
assert damaged_after['score']>damaged_before['score'],damaged_after
assert damaged_after['metrics']['boundary_edges']==0 and damaged_after['metrics']['watertight'] is True,damaged_after
assert damaged_after['metrics']['components']==5,damaged_after

print('LayerVault v0.3.29 Bluebell sheet-pair + duplicate identity + 15-edge recovery: PASS')
