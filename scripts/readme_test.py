"""Validate README structure and project-local assets."""

import re
from pathlib import Path


root = Path(__file__).resolve().parents[1]
readme = (root / "README.md").read_text(encoding="utf-8")

assert readme.startswith('<p align="center">')
assert "# LayerVault" in readme
assert "```mermaid" in readme
assert "AGPL--3.0" in readme
assert "http://localhost:8088" in readme
assert "http://localhost:3004" in readme

references = re.findall(r'(?:src="|\]\()([^"\)]+)', readme)
local_references = [value for value in references if not value.startswith(("http://", "https://", "#"))]
missing = [value for value in local_references if not (root / value).is_file()]
assert not missing, f"Missing README assets: {missing}"

for asset in ("layervault-readme-hero.png", "layervault-dashboard.png"):
    path = root / "docs" / "images" / asset
    assert path.stat().st_size > 100_000, f"README artwork looks incomplete: {asset}"

print(f"LayerVault README presentation and local asset test: PASS ({len(local_references)} links checked)")
