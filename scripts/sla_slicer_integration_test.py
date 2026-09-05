from pathlib import Path
import yaml
root=Path(__file__).resolve().parents[1]
html=(root/'app/templates/index.html').read_text(encoding='utf-8')
js=(root/'app/static/app.js').read_text(encoding='utf-8')
compose=yaml.safe_load((root/'docker-compose.yml').read_text(encoding='utf-8'))
assert 'data-page="sla-slicer"' not in html
assert 'renderSlaSlicer' not in js
assert 'dragonfruit' not in compose['services']
for pack in ('anycubic','elegoo','athena'):
    assert (root/'third_party/dragonfruit/plugins'/pack).is_dir()
print('LayerVault v0.3.29 retired SLA runtime and retained DragonFruit printer artwork: PASS')
