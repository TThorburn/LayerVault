from pathlib import Path

root = Path(__file__).resolve().parents[1]
html = (root / "app/templates/index.html").read_text(encoding="utf-8")
js = (root / "app/static/app.js").read_text(encoding="utf-8")
css = (root / "app/static/styles.css").read_text(encoding="utf-8")

# Banner-free application shell and the current destinations.
assert '<header class="topbar">' not in html
for page in ("dashboard", "library", "projects", "workshop", "materials", "printers", "jobs", "settings"):
    assert f'data-page="{page}"' in html
for retired in ("fdm-slicer", "sla-slicer", "uvtools"):
    assert f'data-page="{retired}"' not in html
assert 'data-sketchforge-url="{{ sketchforge_url }}"' in html

# Eight persistent glass themes, including the final Nebula option.
for theme in ("frost", "midnight", "aurora", "sunset", "ocean", "orchid", "forest", "nebula"):
    assert f"id:'{theme}'" in js
    assert f"theme-preview-{theme}" in css
assert ':root[data-theme="nebula"]' in css
assert "localStorage.getItem('layervault-theme')" in html

# LayerVault's new identity is used both in-app and by the browser.
assert 'branding/layervault-logo-64.png' in html
assert 'branding/layervault-logo-192.png' in html
assert '<div class="brandmark" aria-hidden="true"><img' in html
assert '<div class="brandmark" aria-hidden="true"><svg' not in html
for asset in ("layervault-logo.png", "layervault-logo-512.png", "layervault-logo-192.png", "layervault-logo-64.png"):
    assert (root / "app/static/branding" / asset).is_file()

# Current Workshop and retired runtime UI contract.
assert "async function renderSketchForge()" in js
assert "Formsmith746/SketchForge-3D" in js
assert "no streamed desktop or VNC" in js
assert "renderFdmSlicer" not in js and "renderSlaSlicer" not in js and "renderUvtools" not in js
assert "/api/fdm-slicer/slice" not in js
assert ".fdm-slicer-shell" not in css and ".sla-slicer-shell" not in css and ".uvtools-shell" not in css

# Core polished inventory and print workflows remain available.
assert "printerCatalogModal(" in js and "/api/printer-catalog/search" in js
assert "Open printer artwork & data" in js and "DragonFruit" in js and "OrcaSlicer" in js
assert "jobModelPickerHtml(" in js and "bindJobModelPicker(" in js
assert "newJobFromFileModal(" in js and "/api/jobs/toolpath/inspect" in js
assert "backupScheduleModal(" in js and "/api/settings/backup-schedules" in js
assert "modelSearchPickerHtml(" in js and "project-priority-score" in js
assert ".printer-catalog-results" in css and ".job-model-picker" in css and ".theme-options" in css
assert 'data-upload-title=' in js and 'Files and library names' in js
assert 'id="editMaterialPhoto"' in js and 'Choose replacement photo' in js
assert '.upload-rename-item' in css and '.material-photo-editor' in css
assert 'OpenPrintTag' not in js and 'openprinttag' not in js
assert 'generated-material' in js and '.filament-spool .generated-pack' in css

print("LayerVault v0.3.29 simplified glass UI contract: PASS")
