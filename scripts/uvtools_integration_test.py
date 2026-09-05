from pathlib import Path
import yaml
root=Path(__file__).resolve().parents[1]
html=(root/'app/templates/index.html').read_text(encoding='utf-8')
js=(root/'app/static/app.js').read_text(encoding='utf-8')
compose=yaml.safe_load((root/'docker-compose.yml').read_text(encoding='utf-8'))
assert 'data-page="uvtools"' not in html
assert 'renderUvtools' not in js
assert 'uvtools' not in compose['services']
assert 'uvtools' in js  # printer catalogue data source remains available
print('LayerVault v0.3.29 retired UVtools runtime and retained catalogue source: PASS')
