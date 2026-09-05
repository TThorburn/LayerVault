from pathlib import Path
import yaml
root=Path(__file__).resolve().parents[1]
html=(root/'app/templates/index.html').read_text(encoding='utf-8')
js=(root/'app/static/app.js').read_text(encoding='utf-8')
compose=yaml.safe_load((root/'docker-compose.yml').read_text(encoding='utf-8'))
assert 'data-page="fdm-slicer"' not in html
assert 'renderFdmSlicer' not in js and '/api/fdm-slicer/' not in js
assert 'orcaslicer' not in compose['services']
assert (root/'third_party/printer-artwork/orcaslicer/profiles').is_dir()
assert len(list((root/'third_party/printer-artwork/orcaslicer/profiles').rglob('*_cover.png'))) >= 300
print('LayerVault v0.3.29 retired FDM runtime and retained Orca printer artwork: PASS')
