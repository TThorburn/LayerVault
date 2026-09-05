from pathlib import Path
import io, os, sys, tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='layervault-image-test-')
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app, DB_PATH, CUSTOM_IMAGE_DIR
import sqlite3

c=TestClient(app)
assert c.get('/health').json()['version']=='0.3.29'

def picture(rgb):
    im=Image.new('RGB',(640,480),rgb)
    b=io.BytesIO();im.save(b,'PNG');return b.getvalue()

# Material photo is normalized, cached and reused by matching physical stock.
m1=c.post('/api/materials',json={'name':'Tough Nylon Bottle 1','kind':'Resin','brand':'Phrozen','material':'Engineering Tough Nylon Resin','color':'Lime','color_hex':'#b7e51b'}).json()
r=c.post(f"/api/materials/{m1['id']}/image",files={'file':('resin.png',picture((183,229,27)),'image/png')})
assert r.status_code==200, r.text
m1=r.json(); assert m1['has_custom_image'] and m1['custom_image_asset_id']
img=c.get(f"/api/materials/{m1['id']}/image");assert img.status_code==200 and img.headers['content-type'].startswith('image/webp')
first_asset=m1['custom_image_asset_id']; first_photo=img.content
replacement=c.post(f"/api/materials/{m1['id']}/image",files={'file':('replacement.png',picture((24,84,188)),'image/png')})
assert replacement.status_code==200 and replacement.json()['custom_image_asset_id']!=first_asset
assert c.get(f"/api/materials/{m1['id']}/image").content!=first_photo
m1=replacement.json()
m2=c.post('/api/materials',json={'name':'Tough Nylon Bottle 2','kind':'Resin','brand':'Phrozen','material':'Engineering Tough Nylon Resin','color':'Lime','color_hex':'#b7e51b'}).json()
assert m2['custom_image_asset_id']==m1['custom_image_asset_id'] and m2['has_custom_image']
m3=c.post('/api/materials',json={'name':'Catalogue-linked Tough Nylon','kind':'Resin','brand':'Phrozen','material':'Engineering Tough Nylon Resin','color':'Lime','source_provider':'spoolman','source_key':'phrozen/tough-nylon'}).json()
assert m3['custom_image_asset_id']==m1['custom_image_asset_id']

# Printer photos take priority and are reused by manufacturer/model identity.
p1=c.post('/api/printers',json={'name':'A1 mini workshop','technology':'FDM','manufacturer':'Bambu Lab','model':'A1 mini'}).json()
r=c.post(f"/api/printers/{p1['id']}/image",files={'file':('printer.jpg',picture((220,225,230)),'image/jpeg')})
assert r.status_code==200, r.text
p1=r.json(); assert p1['has_custom_image']
p2=c.post('/api/printers',json={'name':'A1 mini spare','technology':'FDM','manufacturer':'Bambu Lab','model':'A1 mini'}).json()
assert p2['custom_image_asset_id']==p1['custom_image_asset_id']
p3=c.post('/api/printers',json={'name':'A1 mini catalogue copy','technology':'FDM','manufacturer':'Bambu Lab','model':'A1 mini','source_provider':'orca','source_key':'BBL/A1 mini'}).json()
assert p3['custom_image_asset_id']==p1['custom_image_asset_id']
img=c.get(f"/api/printers/{p2['id']}/image");assert img.status_code==200 and img.headers['content-type'].startswith('image/webp')

# Assets are file-backed but indexed/bound by SQLite, so duplicates reuse one cache object.
with sqlite3.connect(DB_PATH) as conn:
    assets=conn.execute('select count(*) from custom_image_assets').fetchone()[0]
    bindings=conn.execute('select count(*) from custom_image_bindings').fetchone()[0]
assert assets==3 and bindings>=4
assert len(list(CUSTOM_IMAGE_DIR.glob('*.webp')))==3
print('LayerVault v0.3.29 reusable inventory image cache: PASS')
