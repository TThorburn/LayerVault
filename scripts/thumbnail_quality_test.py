"""Regression test for dense STL cached previews.

The old renderer kept every Nth triangle and produced a dotted/wire-like card preview for
high-poly miniatures.  A dense continuous mesh should remain visually continuous.
"""
from pathlib import Path
import math
import os
import struct
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='layervault-pass9-thumb-')
from PIL import Image
from app.main import generate_thumbnail, THUMB_RENDER_VERSION


def z(x, y):
    return 2.4 * math.sin(x * 0.08) * math.cos(y * 0.07)

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    stl = td / 'dense-grid.stl'
    out = td / 'dense-grid.webp'
    n = 250  # 125,000 triangles: well beyond the old 18k thumbnail cap.
    tri_count = n * n * 2
    with stl.open('wb') as f:
        f.write(b'LayerVault dense thumbnail regression'.ljust(80, b'\0'))
        f.write(struct.pack('<I', tri_count))
        for iy in range(n):
            y0, y1 = float(iy), float(iy + 1)
            for ix in range(n):
                x0, x1 = float(ix), float(ix + 1)
                v00=(x0,y0,z(x0,y0)); v10=(x1,y0,z(x1,y0)); v01=(x0,y1,z(x0,y1)); v11=(x1,y1,z(x1,y1))
                for a,b,c in ((v00,v10,v11),(v00,v11,v01)):
                    f.write(struct.pack('<12fH', 0.0,0.0,1.0, *a,*b,*c, 0))

    assert generate_thumbnail(stl, out), 'thumbnail generation failed'
    source = Image.open(out); assert source.format == 'WEBP'; img = source.convert('RGBA')
    alpha = img.getchannel('A')
    # Ignore the intentionally faint floor shadow and assess the actual model surface.
    mask = alpha.point(lambda a: 255 if a > 120 else 0)
    bbox = mask.getbbox()
    assert bbox, 'thumbnail contains no rendered model pixels'
    crop = mask.crop(bbox)
    solid = sum(1 for v in crop.getdata() if v)
    occupancy = solid / (crop.width * crop.height)
    assert occupancy > 0.45, f'dense surface is still fragmented (occupancy={occupancy:.3f})'
    alt=td/'dense-grid-alt.webp'; assert generate_thumbnail(stl,alt,view={'yaw_deg':-30,'pitch_deg':28,'zoom':1.05}); assert alt.read_bytes()!=out.read_bytes()
    assert THUMB_RENDER_VERSION == '3'

print('LayerVault Pass 9 dense thumbnail quality test: PASS')
