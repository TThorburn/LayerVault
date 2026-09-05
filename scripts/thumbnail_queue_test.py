"""Exercise the import-time thumbnail queue and immediate browser fallback.

The worker writes previews in the background while a browser may request the same image.
Every response must therefore be a complete, valid WebP rather than a partial file.
"""
from pathlib import Path
import io, os, struct, sys, tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DATA_DIR'] = tempfile.mkdtemp(prefix='layervault-pass9-thumbqueue-')

from PIL import Image
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

def binary_stl(seed: int) -> bytes:
    buf=io.BytesIO()
    buf.write(f'LayerVault queue {seed}'.encode().ljust(80,b'\0'))
    buf.write(struct.pack('<I',1))
    a=(0.0,0.0,0.0); b=(10.0+seed,0.0,0.0); d=(0.0,8.0+seed,float(seed))
    buf.write(struct.pack('<12fH',0.0,0.0,1.0,*a,*b,*d,0))
    return buf.getvalue()

for seed in range(1,9):
    r=c.post('/api/models/upload',files={'file':(f'queue-{seed}.stl',binary_stl(seed),'application/octet-stream')},data={})
    assert r.status_code==200, r.text
    mid=r.json()['model']['id']
    # Ask immediately; this intentionally races the daemon pre-render worker.
    thumb=c.get(f'/api/models/{mid}/thumbnail')
    assert thumb.status_code==200, thumb.text
    assert thumb.headers['content-type'].startswith('image/webp')
    im=Image.open(io.BytesIO(thumb.content))
    assert im.format=='WEBP' and im.size==(640,460)
    im.verify()

print('LayerVault Pass 9 thumbnail queue race test: PASS')
