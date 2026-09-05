from pathlib import Path
import os, struct, sys, tempfile
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='layervault-manufacturing-health-')
from fastapi.testclient import TestClient
from app.main import app


def binary_stl(tris):
    out=bytearray(b'LayerVault manufacturing test'.ljust(80,b'\0'));out+=struct.pack('<I',len(tris))
    for a,b,c in tris:
        out+=struct.pack('<12fH',0,0,0,*a,*b,*c,0)
    return bytes(out)

def box(x,y,z,off=(0,0,0),flip=False):
    ox,oy,oz=off
    v=[(ox,oy,oz),(ox+x,oy,oz),(ox+x,oy+y,oz),(ox,oy+y,oz),(ox,oy,oz+z),(ox+x,oy,oz+z),(ox+x,oy+y,oz+z),(ox,oy+y,oz+z)]
    f=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    if flip:f=[(a,c,b) for a,b,c in f]
    return [tuple(v[i] for i in q) for q in f]

c=TestClient(app)
assert c.get('/health').json()['version']=='0.3.29'
resin=c.post('/api/printers',json={'name':'20um Resin','technology':'MSLA / Resin','build_x':120,'build_y':68,'build_z':150,'resolution_x':6000,'resolution_y':3400,'xy_resolution_x_um':20,'xy_resolution_y_um':20}).json()
fdm=c.post('/api/printers',json={'name':'0.4 FDM','technology':'FDM','build_x':180,'build_y':180,'build_z':180,'nozzle_mm':0.4}).json()

# A true 0.20 mm solid feature is topologically perfect but should be printer-aware thin geometry.
r=c.post('/api/models/upload',files={'file':('thin-feature.stl',binary_stl(box(10,10,.2)),'model/stl')},data={'title':'Thin exposed feature'})
assert r.status_code==200,r.text; mid=r.json()['model']['id']
mesh=c.get(f'/api/models/{mid}/health').json();assert mesh['grade']=='Healthy' and mesh['score']==100
rh=c.get(f'/api/models/{mid}/health',params={'printer_id':resin['id']}).json();pm=rh['manufacturing']
assert pm['technology']=='Resin' and pm['grade'] in ('Review','Issues'),pm
assert pm['thickness']['available'] is True and pm['thickness']['estimated_p05_mm'] <= .21
assert any(x['code'] in ('thin_exposed_feature','thin_geometry','critical_thickness') for x in pm['issues'])
assert any(x.get('markers') for x in pm['issues'] if x['code'] in ('thin_exposed_feature','thin_geometry','critical_thickness'))
fh=c.get(f'/api/models/{mid}/health',params={'printer_id':fdm['id']}).json()['manufacturing']
assert fh['technology']=='FDM' and any(x['code']=='critical_thickness' for x in fh['issues'])

# Two thick solids facing across a 0.20 mm air gap are not a thin wall. This is the exact false
# positive that previously highlighted close connected folds and outfit detail.
air_gap = box(10,10,2) + box(10,10,2,(0,0,2.2))
r=c.post('/api/models/upload',files={'file':('close-air-gap.stl',binary_stl(air_gap),'model/stl')},data={'title':'Close surfaces across air'})
assert r.status_code==200,r.text; gap_id=r.json()['model']['id']
gap=c.get(f'/api/models/{gap_id}/health',params={'printer_id':resin['id']}).json()['manufacturing']
assert not any(x['code']=='thin_exposed_feature' for x in gap['issues']),gap
assert gap['resin']['preparation']['can_thicken_broad_regions'] is False,gap

# Nested outer + reversed inner closed shell represents a classic sealed hollow cavity.
outer=box(20,20,20);inner=box(10,10,10,(5,5,5),True)
r=c.post('/api/models/upload',files={'file':('sealed-hollow.stl',binary_stl(outer+inner),'model/stl')},data={'title':'Sealed hollow'})
assert r.status_code==200,r.text; hid=r.json()['model']['id']
h=c.get(f'/api/models/{hid}/health',params={'printer_id':resin['id']}).json()['manufacturing']
assert h['resin']['enclosed_cavities']['candidate_count']>=1,h
assert any(x['code']=='trapped_resin' for x in h['issues'])
assert 'suction_pockets' in h['resin'] and 'unsupported_minima' in h['resin'] and 'peel_proxy' in h['resin']


# An intentionally open downward-facing cup shape should trigger the low-confidence suction screening.
def suction_cup_tris(n=20):
    tris=[]
    def quad(a,b,c,d,flip=False):
        if flip: tris.extend([(a,c,b),(a,d,c)])
        else: tris.extend([(a,b,c),(a,c,d)])
    for i in range(n):
        for j in range(n):
            x0=2+6*i/n;x1=2+6*(i+1)/n;y0=2+6*j/n;y1=2+6*(j+1)/n
            quad((x0,y0,10),(x1,y0,10),(x1,y1,10),(x0,y1,10),True)
    for k in range(n):
        z0=10*k/n;z1=10*(k+1)/n
        quad((2,2,z0),(2,8,z0),(2,8,z1),(2,2,z1))
        quad((8,8,z0),(8,2,z0),(8,2,z1),(8,8,z1))
        quad((8,2,z0),(2,2,z0),(2,2,z1),(8,2,z1))
        quad((2,8,z0),(8,8,z0),(8,8,z1),(2,8,z1))
    return tris

r=c.post('/api/models/upload',files={'file':('suction-cup.stl',binary_stl(suction_cup_tris()),'model/stl')},data={'title':'Downward cup'})
assert r.status_code==200,r.text; cid=r.json()['model']['id']
ch=c.get(f'/api/models/{cid}/health',params={'printer_id':resin['id']}).json()['manufacturing']
assert ch['resin']['suction_pockets']['candidate_count']>=1,ch
assert any(x['code']=='suction_pocket' for x in ch['issues'])

# FDM report must include technology-specific overhang/bridge/bed-contact screening.
assert 'overhangs' in fh['fdm'] and 'unsupported_minima' in fh['fdm']

# Manufacturing reports are cached separately per selected printer.
second=c.get(f'/api/models/{mid}/health',params={'printer_id':resin['id']}).json()['manufacturing']
assert second['analyzed_at']==pm['analyzed_at']

# Editing printer-critical parameters invalidates its cached manufacturing report.
old_sig=fh['printer_signature']
c.patch(f"/api/printers/{fdm['id']}",json={'nozzle_mm':0.6})
fh_changed=c.get(f'/api/models/{mid}/health',params={'printer_id':fdm['id']}).json()['manufacturing']
assert fh_changed['printer_signature'] != old_sig
assert fh_changed['thickness']['critical_threshold_mm'] > fh['thickness']['critical_threshold_mm']

print('LayerVault v0.3.29 inward-material manufacturing-health regression: PASS')
