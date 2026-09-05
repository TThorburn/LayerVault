import os, tempfile, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='lv0114-refine-')
from fastapi.testclient import TestClient
from app.main import app

root=Path(__file__).resolve().parents[1]
js=(root/'app/static/app.js').read_text(encoding='utf-8')
css=(root/'app/static/styles.css').read_text(encoding='utf-8')
c=TestClient(app)

r=c.get('/')
assert r.status_code == 200
assert r.headers.get('cache-control','').startswith('no-store')
assert 'window.__LAYERVAULT_SHOW_BOOT_FAILURE__' in r.text
assert 'window.__LAYERVAULT_READY__ = true' in r.text
assert 'let threeEnginePromise = null' in r.text
assert 'id="layervault-core-styles"' in r.text
assert ':root {' in r.text and '.sidebar' in r.text
assert r.headers.get('pragma') == 'no-cache'
assets=c.get('/health/assets')
assert assets.status_code == 200 and assets.json()['ok'] is True
assert assets.json()['css_embedded'] is True and assets.json()['js_embedded'] is True
assert assets.json()['css_bytes'] > 100000 and assets.json()['js_bytes'] > 150000

assert 'async function renderSketchForge()' in js and 'Formsmith746/SketchForge-3D' in js
assert 'data-selected-objects' not in js
assert 'Upload photo' in js and 'Replace photo' in js
assert 'printer-detail-hero' in js and 'hardware-capability-strip' in js
assert 'inventory-detail-top' in js and 'material-photo-placeholder' in js
assert 'materialQrModal' in js and 'Inventory QR label' in js
assert '.modal-card:has(.printer-detail-polished)' in css

# Verify the QR action we rediscovered during the polish pass still has a working endpoint.
m=c.post('/api/materials',json={'name':'Test PLA','kind':'Filament','material':'PLA','initial_amount':1000,'remaining_amount':1000,'unit':'g'}).json()
qr=c.get(f"/api/materials/{m['id']}/qr")
assert qr.status_code == 200 and qr.headers['content-type'].startswith('image/png')

print('LayerVault v0.3.29 final refinement regression: PASS')
