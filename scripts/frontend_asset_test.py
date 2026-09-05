import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='lv0201-assets-')
from fastapi.testclient import TestClient
from app.main import app

c=TestClient(app)
r=c.get('/')
assert r.status_code == 200
assert r.headers.get('cache-control','').startswith('no-store')
assert r.headers.get('pragma') == 'no-cache'
assert 'id="layervault-core-styles"' in r.text
assert ':root {' in r.text
assert '.sidebar {' in r.text or '.sidebar{' in r.text
assert 'window.__LAYERVAULT_SHOW_BOOT_FAILURE__' in r.text
assert 'window.__LAYERVAULT_READY__ = true' in r.text
assert 'let threeEnginePromise = null' in r.text
assert 'safeStorageGet' in r.text and "localStorage.getItem('layervault-library-view')" not in r.text
# Styles are embedded, so a separate stylesheet request is no longer required for usable rendering.
assert '<link rel="stylesheet"' not in r.text
a=c.get('/health/assets')
assert a.status_code == 200
j=a.json()
assert j['ok'] is True and j['version']=='0.3.29' and j['css_embedded'] is True and j['js_embedded'] is True
assert j['css_bytes'] > 100000 and j['js_bytes'] > 150000
assert j['assets']['styles.css']['ok'] is True
assert j['assets']['styles.css']['sha256']
assert j['assets']['app.js']['ok'] is True
assert j['assets']['app.js']['sha256']
assert j['workshop_ok'] is True
assert j['assets']['manifold.js']['ok'] is True and j['assets']['manifold.wasm']['ok'] is True
css=c.get('/static/styles.css?v=0.3.29')
assert css.status_code == 200 and css.headers['content-type'].startswith('text/css')
js=c.get('/static/app.js?v=0.3.29')
assert js.status_code == 200 and "import * as THREE" not in js.text and "import('three')" in js.text
print('LayerVault v0.3.29 frontend asset delivery regression: PASS')
