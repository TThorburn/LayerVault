from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

_CACHE_DIR: Path | None = None
_IMAGE_DIR: Path | None = None
_FIXTURE_DIR: Path | None = None

PROVIDER_INFO = {
    "spoolman": {
        "id": "spoolman",
        "name": "SpoolmanDB",
        "technology": "FDM",
        "description": "Community filament catalogue with density, package size, colour and manufacturer temperature guidance.",
        "license": "MIT",
        "homepage": "https://github.com/Donkie/SpoolmanDB",
    },
    "openresin": {
        "id": "openresin",
        "name": "Open Resin Alliance",
        "technology": "Resin",
        "description": "Printer-specific resin starting profiles from the open DragonFruit ecosystem.",
        "license": "MIT material plugins",
        "homepage": "https://github.com/Open-Resin-Alliance",
    },
    "manufacturer_resin": {
        "id": "manufacturer_resin",
        "name": "Official Resin Catalogues",
        "technology": "Resin",
        "description": "Searchable product families from major resin manufacturers, with links back to each official catalogue.",
        "license": "Manufacturer product names and links",
        "homepage": "https://store.anycubic.com/pages/resin-user-manual",
    },
}

# Material-profile repositories that currently publish DragonFruit material files.
# The provider code is intentionally data-driven so more repositories can be added
# without changing the API/UI contract.
ORA_MATERIAL_REPOS = ["df-plugin-sirayatech"]
_MANUFACTURER_CATALOG_PATH = Path(__file__).with_name("resin_catalog.json")

# Curated links remain deliberately small and point only to official manufacturer
# pages. Product artwork is discovered from each page's OpenGraph metadata and
# cached locally; LayerVault does not redistribute a third-party catalogue dump.
OFFICIAL_MATERIAL_PAGES: list[dict[str, Any]] = [
    {"brands": ("anycubic",), "terms": ("16k standard resin",), "mode": "exact", "kind": "resin", "url": "https://store.anycubic.com/products/16k-standard-resin", "specs": {"wavelength_nm": "365–405", "bottom_exposure_s": "20–40", "density_g_cm3": "1.05–1.10", "hardness": "83–85 HD", "viscosity_mpas": "500–600"}},
    {"brands": ("anycubic",), "terms": ("standard resin v2",), "mode": "exact", "kind": "resin", "url": "https://store.anycubic.com/collections/uv-resin/products/standard-resin-v2", "specs": {"wavelength_nm": "365–405", "normal_exposure_s": "2.5–3", "bottom_exposure_s": "20–40", "density_g_cm3": "1.05–1.25"}},
    {"brands": ("anycubic",), "terms": ("standard resin",), "mode": "exact", "kind": "resin", "url": "https://store.anycubic.com/products/colored-uv-resin", "specs": {"wavelength_nm": "365–405"}},
    {"brands": ("anycubic",), "terms": ("abs-like resin 2.0",), "mode": "exact", "kind": "resin", "url": "https://store.anycubic.com/products/abs-like-resin-2-0", "specs": {"wavelength_nm": "365–405"}},
    {"brands": ("anycubic",), "terms": ("abs-like resin pro 2",), "mode": "exact", "kind": "resin", "url": "https://store.anycubic.com/products/abs-like-resin-pro-2", "specs": {"wavelength_nm": "365–405"}},
    {"brands": ("anycubic",), "terms": ("abs-like resin 3.0",), "mode": "exact", "kind": "resin", "url": "https://store.anycubic.com/products/abs-like-resin-3-0", "specs": {"wavelength_nm": "365–405"}},
    {"brands": ("anycubic",), "terms": ("water-wash resin 2.0",), "mode": "exact", "kind": "resin", "url": "https://store.anycubic.com/products/water-wash-resin", "specs": {"wavelength_nm": "365–405", "cleaning": "Water washable"}},
    {"brands": ("anycubic",), "terms": ("high speed resin 2.0",), "mode": "exact", "kind": "resin", "url": "https://store.anycubic.com/products/high-speed-resin-2", "specs": {"wavelength_nm": "365–405"}},
    {"brands": ("anycubic",), "terms": ("tough resin 2.0",), "mode": "exact", "kind": "resin", "url": "https://store.anycubic.com/products/tough-resin-2", "specs": {"wavelength_nm": "365–405"}},
    {"brands": ("anycubic",), "terms": ("high clear resin",), "mode": "exact", "kind": "resin", "url": "https://store.anycubic.com/products/high-clear-resin", "specs": {"wavelength_nm": "365–405"}},
    {"brands": ("elegoo",), "terms": ("8k abs-like resin v3.0",), "mode": "exact", "kind": "resin", "url": "https://us.elegoo.com/collections/resin/products/elegoo-8k-abs-like-resin-v-3-0", "specs": {"wavelength_nm": "405"}},
    {"brands": ("elegoo",), "terms": ("water-washable resin",), "mode": "exact", "kind": "resin", "url": "https://www.elegoo.com/en-gb/collections/materials/products/elegoo-water-washable-resin", "specs": {"wavelength_nm": "405", "cleaning": "Water washable"}},
    {"brands": ("elegoo",), "terms": ("water-washable resin v2.0",), "mode": "exact", "kind": "resin", "url": "https://www.elegoo.com/en-gb/collections/elegoo-products-10off/products/elegoo-water-washable-resin-v-2-0", "specs": {"wavelength_nm": "405", "cleaning": "Water washable"}},
    {"brands": ("elegoo",), "terms": ("standard resin v2.0",), "mode": "exact", "kind": "resin", "url": "https://www.elegoo.com/collections/standard-resins/products/elegoo-standard-resin-v-2-0", "specs": {"wavelength_nm": "405"}},
    {"brands": ("sunlu",), "terms": ("standard resin",), "mode": "exact", "kind": "resin", "url": "https://www.sunlu.com/products/standard-3d-printing-resin", "specs": {"wavelength_nm": "405", "normal_exposure_s": "1.5–3.5", "bottom_exposure_s": "10–50"}},
    {"brands": ("sunlu",), "terms": ("abs-like resin",), "mode": "exact", "kind": "resin", "url": "https://www.sunlu.com/products/283", "specs": {"wavelength_nm": "405"}},
    {"brands": ("sunlu",), "terms": ("water-wash standard resin",), "mode": "exact", "kind": "resin", "url": "https://www.sunlu.com/products/water-wash-standard-resin", "specs": {"wavelength_nm": "405", "cleaning": "Water washable"}},
    {"brands": ("sunlu",), "terms": ("water-wash abs-like resin",), "mode": "exact", "kind": "resin", "url": "https://www.sunlu.com/products/water-wash-abs-like-resin", "specs": {"wavelength_nm": "405", "cleaning": "Water washable"}},
    {"brands": ("bambu lab", "bambu"), "terms": ("pla basic",), "mode": "exact", "kind": "filament", "url": "https://us.store.bambulab.com/products/pla-basic-filament", "specs": {"diameter_mm": 1.75, "diameter_tolerance_mm": 0.03, "package_weight_g": 1000, "drying": "50°C for 8h (oven)", "max_print_speed_mms": 258}},
    {"brands": ("bambu lab", "bambu"), "terms": ("abs",), "mode": "exact", "kind": "filament", "url": "https://us.store.bambulab.com/products/abs-filament", "specs": {"diameter_mm": 1.75, "diameter_tolerance_mm": 0.03, "package_weight_g": 1000}},
    {"brands": ("bambu lab", "bambu"), "terms": ("asa",), "mode": "exact", "kind": "filament", "url": "https://us.store.bambulab.com/products/asa-filament", "specs": {"diameter_mm": 1.75, "diameter_tolerance_mm": 0.03, "package_weight_g": 1000, "nozzle_temp_c": "240–270", "bed_temp_c": "80–100", "max_print_speed_mms": 250}},
    {"brands": ("bambu lab", "bambu"), "terms": ("tpu 85a", "tpu 90a"), "mode": "exact", "kind": "filament", "url": "https://us.store.bambulab.com/products/tpu-85a-tpu-90a/", "specs": {"diameter_mm": 1.75, "package_weight_g": 1000}},
    {"brands": ("prusament", "prusa"), "terms": ("petg",), "mode": "prefix", "kind": "filament", "url": "https://www.prusa3d.com/en/product/prusament-petg-filament/", "specs": {"diameter_mm": 1.75, "diameter_tolerance_mm": 0.02, "package_weight_g": 1000}},
    {"brands": ("prusament", "prusa"), "terms": ("asa",), "mode": "prefix", "kind": "filament", "url": "https://www.prusa3d.com/product/prusament-asa-filament/", "specs": {"diameter_mm": 1.75, "diameter_tolerance_mm": 0.04, "nozzle_temp_c": "255–265", "bed_temp_c": "105–115", "package_weight_g": 1000}},
    {"brands": ("prusament", "prusa"), "terms": ("pla",), "mode": "prefix", "kind": "filament", "url": "https://www.prusa3d.com/product/prusament-pla-filament/", "specs": {"diameter_mm": 1.75, "diameter_tolerance_mm": 0.02, "nozzle_temp_c": 215, "bed_temp_c": "50–60", "package_weight_g": 1000}},
    {"brands": ("anycubic",), "terms": ("pla+", "pla plus"), "mode": "exact", "kind": "filament", "url": "https://store.anycubic.com/products/pla-plus-filament", "specs": {"diameter_mm": 1.75, "package_weight_g": 1000}},
    {"brands": ("anycubic",), "terms": ("pla basic", "pla"), "mode": "exact", "kind": "filament", "url": "https://store.anycubic.com/products/pla-filament", "specs": {"diameter_mm": 1.75, "nozzle_temp_c": "190–230", "bed_temp_c": "55–65", "package_weight_g": 1000}},
    {"brands": ("anycubic",), "terms": ("petg",), "mode": "exact", "kind": "filament", "url": "https://store.anycubic.com/products/petg-filament", "specs": {"diameter_mm": 1.75, "package_weight_g": 1000}},
    {"brands": ("anycubic",), "terms": ("asa",), "mode": "exact", "kind": "filament", "url": "https://store.anycubic.com/products/asa-filament", "specs": {"diameter_mm": 1.75, "package_weight_g": 1000}},
    {"brands": ("deeplee",), "terms": ("rapid pla+", "rapid pla", "pla"), "mode": "exact", "kind": "filament", "url": "https://deeplee3d.com/", "specs": {"diameter_mm": 1.75, "diameter_tolerance_mm": 0.02, "package_weight_g": 1000, "max_print_speed_mms": 600}},
]


def configure(data_dir: Path) -> None:
    global _CACHE_DIR, _IMAGE_DIR, _FIXTURE_DIR
    _CACHE_DIR = Path(data_dir) / "catalog-cache"
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _IMAGE_DIR = _CACHE_DIR / "material-images"
    _IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    fixture = os.getenv("CATALOG_FIXTURE_DIR", "").strip()
    _FIXTURE_DIR = Path(fixture) if fixture else None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def _pretty_slug(s: str) -> str:
    words = [w for w in re.split(r"[-_]+", s or "") if w]
    special = {"pla": "PLA", "petg": "PETG", "asa": "ASA", "abs": "ABS", "tpu": "TPU", "pc": "PC", "pa": "PA", "uv": "UV", "cf": "CF", "gf": "GF"}
    return " ".join(special.get(w.lower(), w.capitalize()) for w in words)


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", key)[:180]


def _fixture_text(key: str) -> str | None:
    if not _FIXTURE_DIR:
        return None
    for suffix in ("", ".json", ".yaml", ".yml", ".txt"):
        p = _FIXTURE_DIR / f"{_safe_key(key)}{suffix}"
        if p.exists():
            return p.read_text(encoding="utf-8")
    return None


def _fixture_bytes(key: str) -> bytes | None:
    if not _FIXTURE_DIR:
        return None
    for suffix in ("", ".png", ".jpg", ".jpeg", ".webp"):
        p = _FIXTURE_DIR / f"{_safe_key(key)}{suffix}"
        if p.exists():
            return p.read_bytes()
    return None


def _official_material(brand: str, name: str, material: str, kind: str) -> dict[str, Any] | None:
    maker = re.sub(r"[^a-z0-9]+", " ", (brand or "").casefold()).strip()
    products = [re.sub(r"[^a-z0-9+]+", " ", value.casefold()).strip() for value in (str(name or ""), str(material or "")) if value]
    family = "resin" if "resin" in (kind or "").casefold() else "filament"
    for item in OFFICIAL_MATERIAL_PAGES:
        if item["kind"] != family or maker not in item["brands"]:
            continue
        candidates: list[str] = []
        for product in products:
            candidates.append(product)
            for alias in item["brands"]:
                if product.startswith(alias + " "):
                    candidates.append(product[len(alias):].strip())
        terms = [re.sub(r"[^a-z0-9+]+", " ", term.casefold()).strip() for term in item["terms"]]
        mode = item.get("mode", "contains")
        if (mode == "exact" and any(product in terms for product in candidates)) or (mode == "prefix" and any(product.startswith(term) for product in candidates for term in terms)) or (mode == "contains" and any(term in product for product in candidates for term in terms)):
            return item
    return None


def official_artwork(brand: str, name: str, material: str, kind: str, color: str = "") -> dict[str, Any] | None:
    item = _official_material(brand, name, material, kind)
    if not item:
        return None
    # Shopify's product-level OpenGraph image normally represents one default
    # colour.  Using it for every colour created misleading orange-spool/green-
    # filament cards.  Keep the official page and specifications, but use the
    # accurate colour-driven fallback until a user supplies an exact photo.
    allow_product_image = item["kind"] == "resin" or not str(color or "").strip()
    return {
        "url": item["url"] if allow_product_image else "",
        "product_url": item["url"],
        "specs": dict(item.get("specs") or {}),
    }


def _og_image_url(page_url: str) -> str:
    host = (urlparse(page_url).hostname or "").casefold()
    trusted = {"store.anycubic.com", "www.elegoo.com", "us.elegoo.com", "www.sunlu.com", "store.sunlu.com", "us.store.bambulab.com", "www.prusa3d.com", "deeplee3d.com"}
    if host not in trusted or urlparse(page_url).scheme != "https":
        raise RuntimeError("Product artwork page is not an approved manufacturer source")
    key = "official-page-" + hashlib.sha1(page_url.encode()).hexdigest()
    page = _fetch_text(key, page_url, ttl=7 * 24 * 3600)
    patterns = (
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, page, re.I)
        if match:
            return urljoin(page_url, html.unescape(match.group(1).strip()))
    raise RuntimeError("Official product page did not publish an artwork image")


def _fetch_image(key: str, url: str, ttl: int = 30 * 24 * 3600) -> tuple[bytes, str]:
    fixture = _fixture_bytes(key)
    if fixture is not None:
        return fixture, "image/png"
    if _IMAGE_DIR is None:
        raise RuntimeError("Material image cache is not configured")
    body_path = _IMAGE_DIR / f"{_safe_key(key)}.bin"
    meta_path = _IMAGE_DIR / f"{_safe_key(key)}.json"
    if body_path.exists() and meta_path.exists() and time.time() - body_path.stat().st_mtime < ttl:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return body_path.read_bytes(), str(meta.get("content_type") or "image/jpeg")
    headers = {"User-Agent": "LayerVault-material-artwork/0.3", "Accept": "image/avif,image/webp,image/png,image/jpeg"}
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/") or len(response.content) > 12 * 1024 * 1024:
            raise RuntimeError("Official product artwork was not a supported image")
        payload = response.content
    tmp = body_path.with_suffix(".tmp")
    tmp.write_bytes(payload); tmp.replace(body_path)
    meta_path.write_text(json.dumps({"content_type": content_type, "source": url}), encoding="utf-8")
    return payload, content_type


def _fetch_text(key: str, url: str, ttl: int = 24 * 3600) -> str:
    fixture = _fixture_text(key)
    if fixture is not None:
        return fixture
    if _CACHE_DIR is None:
        raise RuntimeError("Material catalogue not configured")
    cache = _CACHE_DIR / f"{_safe_key(key)}.cache"
    if cache.exists() and time.time() - cache.stat().st_mtime < ttl:
        return cache.read_text(encoding="utf-8")
    headers = {"User-Agent": "LayerVault-material-catalog/0.2.1", "Accept": "application/json,text/plain,*/*"}
    try:
        with httpx.Client(timeout=25.0, follow_redirects=True, headers=headers) as client:
            r = client.get(url)
            r.raise_for_status()
            text = r.text
        tmp = cache.with_suffix(cache.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(cache)
        return text
    except Exception as exc:
        if cache.exists():
            return cache.read_text(encoding="utf-8")
        raise RuntimeError(f"Could not reach material source: {exc}") from exc


def _fetch_json(key: str, url: str, ttl: int = 24 * 3600) -> Any:
    return json.loads(_fetch_text(key, url, ttl))


def _score_text(query: str, *parts: Any) -> int:
    q = (query or "").strip().casefold()
    if not q:
        return 1
    hay = " ".join(str(x or "") for x in parts).casefold()
    toks = [t for t in re.split(r"\s+", q) if t]
    if not all(t in hay for t in toks):
        return 0
    score = 10
    if q in hay:
        score += 10
    for p in parts:
        s = str(p or "").casefold()
        if s == q:
            score += 20
        elif s.startswith(q):
            score += 8
    return score


def _first_number(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, list) and v:
        vals = [float(x) for x in v if isinstance(x, (int, float))]
        return sum(vals) / len(vals) if vals else None
    return None


def _colour_hex(v: Any) -> str:
    if not v:
        return "#808080"
    if isinstance(v, list):
        v = v[0] if v else ""
    s = str(v).strip()
    if not s:
        return "#808080"
    if not s.startswith("#"):
        s = "#" + s
    if len(s) == 9:  # RGBA -> RGB for LayerVault chip
        s = s[:7]
    return s if re.fullmatch(r"#[0-9a-fA-F]{6}", s) else "#808080"


def _source_meta(provider: str, key: str, url: str, raw: Any) -> dict[str, Any]:
    return {
        "source_provider": provider,
        "source_key": key,
        "source_url": url,
        "source_snapshot": raw if isinstance(raw, dict) else {"raw": raw},
    }


def _decorate_official_artwork(item: dict[str, Any]) -> dict[str, Any]:
    """Attach official artwork and a normalized, useful specification snapshot."""
    official = _official_material(str(item.get("brand") or ""), str(item.get("name") or ""), str(item.get("material") or ""), str(item.get("kind") or ""))
    specs: dict[str, Any] = dict((official or {}).get("specs") or {})
    if item.get("density") is not None: specs.setdefault("density_g_cm3", item["density"])
    if item.get("diameter_mm") is not None: specs.setdefault("diameter_mm", item["diameter_mm"])
    if item.get("spool_weight_g") is not None: specs.setdefault("empty_spool_weight_g", item["spool_weight_g"])
    if item.get("package_amount") is not None: specs.setdefault("package_amount", item["package_amount"])
    if item.get("package_unit"): specs.setdefault("package_unit", item["package_unit"])
    ranges = item.get("recommended_ranges") or {}
    if ranges.get("nozzle_c") is not None: specs.setdefault("nozzle_temp_c", ranges["nozzle_c"])
    if ranges.get("bed_c") is not None: specs.setdefault("bed_temp_c", ranges["bed_c"])
    raw = item.get("raw") or {}
    for src, dest in (("finish", "finish"), ("pattern", "pattern"), ("translucent", "translucent"), ("glow", "glow"), ("spool_type", "spool_type")):
        if raw.get(src) not in (None, "", False): specs.setdefault(dest, raw[src])
    item["specs"] = specs
    payload = item.get("material_payload")
    if isinstance(payload, dict):
        payload["specs"] = specs
    allow_product_image = bool(official) and (str(item.get("kind") or "").casefold() == "resin" or not str(item.get("color") or "").strip())
    if official:
        page = str(official["url"])
        item["has_image"] = allow_product_image
        if allow_product_image:
            item["image_page_url"] = page
        item["official_product_url"] = page
        if isinstance(payload, dict):
            if allow_product_image:
                payload["source_image_url"] = page
            payload.setdefault("product_url", page)
    else:
        item.setdefault("has_image", False)
    return item


# ---------------- Official manufacturer resin index ----------------

def _manufacturer_resins() -> tuple[list[dict[str, Any]], str]:
    """Return the bundled, offline-safe index of official resin product families."""
    try:
        data = json.loads(_MANUFACTURER_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read the manufacturer resin index: {exc}") from exc
    products = data.get("products") if isinstance(data, dict) else []
    if not isinstance(products, list):
        products = []
    out: list[dict[str, Any]] = []
    for raw in products:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        brand = str(item.get("brand") or "").strip()
        name = str(item.get("name") or "").strip()
        if not brand or not name:
            continue
        item["_key"] = f"{_slug(brand)}--{_slug(name)}"
        out.append(item)
    return out, str(data.get("reviewed_at") or "") if isinstance(data, dict) else ""


def _manufacturer_resin_detail(key: str) -> dict[str, Any]:
    products, reviewed_at = _manufacturer_resins()
    raw = next((item for item in products if item.get("_key") == key), None)
    if raw is None:
        raise KeyError("Manufacturer resin product not found")
    brand = str(raw.get("brand") or "")
    name = str(raw.get("name") or "Resin")
    family = str(raw.get("family") or "Resin")
    source_url = str(raw.get("url") or PROVIDER_INFO["manufacturer_resin"]["homepage"])
    snapshot = {k: v for k, v in raw.items() if not k.startswith("_")}
    snapshot["catalog_reviewed_at"] = reviewed_at
    meta = _source_meta("manufacturer_resin", key, source_url, snapshot)
    return {
        "provider": PROVIDER_INFO["manufacturer_resin"], "key": key, "brand": brand, "name": name,
        "technology": "Resin", "kind": "Resin", "material": family, "color": "", "color_hex": "#8ed7ca",
        "package_amount": 1000, "package_unit": "ml", "density": None, "settings": {}, "has_profile": False,
        "source_url": source_url, "catalog_reviewed_at": reviewed_at,
        "material_payload": {
            "name": f"{brand} · {name}", "kind": "Resin", "material": family, "brand": brand,
            "color": "", "color_hex": "#8ed7ca", "initial_amount": 1000, "remaining_amount": 1000,
            "unit": "ml", "product_url": source_url, **meta,
        },
        "profile_payload": None,
        "raw": snapshot,
    }


# ---------------- SpoolmanDB ----------------

def _expand_spoolman_group(group: dict[str, Any]) -> list[dict[str, Any]]:
    manufacturer = group.get("manufacturer") or group.get("vendor") or ""
    filaments = group.get("filaments") or []
    out: list[dict[str, Any]] = []
    for f in filaments:
        colors = f.get("colors") or [{}]
        weights = f.get("weights") or [{}]
        diameters = f.get("diameters") or [1.75]
        for c in colors:
            for w in weights:
                for dia in diameters:
                    name = str(f.get("name") or f.get("material") or "Filament")
                    cname = c.get("name") or ""
                    name = name.replace("{color_name}", cname).strip()
                    out.append({
                        "manufacturer": manufacturer,
                        "name": name,
                        "material": f.get("material") or "",
                        "density": f.get("density"),
                        "weight": w.get("weight"),
                        "spool_weight": w.get("spool_weight"),
                        "spool_type": w.get("spool_type"),
                        "diameter": dia,
                        "extruder_temp": f.get("extruder_temp"),
                        "extruder_temp_range": f.get("extruder_temp_range"),
                        "bed_temp": f.get("bed_temp"),
                        "bed_temp_range": f.get("bed_temp_range"),
                        "color_name": cname,
                        "color_hex": c.get("hex") or (c.get("hexes") or [""])[0],
                        "finish": c.get("finish") or f.get("finish"),
                        "pattern": c.get("pattern") or f.get("pattern"),
                        "translucent": c.get("translucent", f.get("translucent")),
                        "glow": c.get("glow", f.get("glow")),
                    })
    return out


def _normalize_spoolman_flat(item: dict[str, Any]) -> dict[str, Any]:
    vendor = item.get("manufacturer") or item.get("vendor") or item.get("vendor_name") or ""
    if isinstance(vendor, dict):
        vendor = vendor.get("name") or ""
    return {
        "manufacturer": vendor,
        "name": item.get("name") or item.get("filament_name") or item.get("material") or "Filament",
        "material": item.get("material") or "",
        "density": item.get("density"),
        "weight": item.get("weight") or item.get("nominal_weight"),
        "spool_weight": item.get("spool_weight"),
        "spool_type": item.get("spool_type"),
        "diameter": item.get("diameter") or item.get("filament_diameter") or 1.75,
        "extruder_temp": item.get("extruder_temp") or item.get("settings_extruder_temp"),
        "extruder_temp_range": item.get("extruder_temp_range"),
        "bed_temp": item.get("bed_temp") or item.get("settings_bed_temp"),
        "bed_temp_range": item.get("bed_temp_range"),
        "color_name": item.get("color_name") or item.get("color") or "",
        "color_hex": item.get("color_hex") or item.get("hex") or "",
        "finish": item.get("finish"),
        "pattern": item.get("pattern"),
        "translucent": item.get("translucent"),
        "glow": item.get("glow"),
    }


def _spoolman_entries() -> list[dict[str, Any]]:
    data = _fetch_json("spoolman-filaments", "https://donkie.github.io/SpoolmanDB/filaments.json")
    out: list[dict[str, Any]] = []
    if isinstance(data, dict) and "manufacturer" in data and "filaments" in data:
        out.extend(_expand_spoolman_group(data))
    elif isinstance(data, dict):
        for manufacturer, val in data.items():
            if isinstance(val, dict) and "filaments" in val:
                g = dict(val); g.setdefault("manufacturer", manufacturer); out.extend(_expand_spoolman_group(g))
            elif isinstance(val, list):
                out.extend(_normalize_spoolman_flat({**x, "manufacturer": manufacturer}) for x in val if isinstance(x, dict))
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            if "filaments" in item:
                out.extend(_expand_spoolman_group(item))
            else:
                out.append(_normalize_spoolman_flat(item))
    # Stable provider keys survive cache refreshes as long as product identity does.
    for x in out:
        identity = json.dumps({k: x.get(k) for k in ("manufacturer", "name", "material", "weight", "diameter", "color_name")}, sort_keys=True)
        x["_key"] = hashlib.sha1(identity.encode()).hexdigest()
    return out


def _spoolman_detail_from_entry(x: dict[str, Any]) -> dict[str, Any]:
    nozzle = _first_number(x.get("extruder_temp")) or _first_number(x.get("extruder_temp_range"))
    bed = _first_number(x.get("bed_temp")) or _first_number(x.get("bed_temp_range"))
    settings: dict[str, Any] = {}
    if nozzle is not None: settings["nozzle_temp_c"] = round(nozzle, 2)
    if bed is not None: settings["bed_temp_c"] = round(bed, 2)
    raw = {k: v for k, v in x.items() if not k.startswith("_")}
    url = "https://github.com/Donkie/SpoolmanDB"
    meta = _source_meta("spoolman", x["_key"], url, raw)
    weight = float(x.get("weight") or 1000)
    brand = str(x.get("manufacturer") or "")
    name = str(x.get("name") or x.get("material") or "Filament")
    material_name = str(x.get("material") or "Filament")
    color = str(x.get("color_name") or "")
    return {
        "provider": PROVIDER_INFO["spoolman"], "key": x["_key"], "brand": brand, "name": name,
        "technology": "FDM", "kind": "Filament", "material": material_name, "color": color,
        "color_hex": _colour_hex(x.get("color_hex")), "density": x.get("density"), "diameter_mm": x.get("diameter"),
        "package_amount": weight, "package_unit": "g", "spool_weight_g": x.get("spool_weight"),
        "recommended_ranges": {"nozzle_c": x.get("extruder_temp_range"), "bed_c": x.get("bed_temp_range")},
        "settings": settings, "has_profile": bool(settings), "source_url": url,
        "material_payload": {
            "name": " · ".join(v for v in (brand, name) if v), "kind": "Filament", "material": material_name,
            "brand": brand, "color": color, "color_hex": _colour_hex(x.get("color_hex")), "density_g_cm3": x.get("density"),
            "diameter_mm": x.get("diameter"), "initial_amount": weight, "remaining_amount": weight, "unit": "g", **meta,
        },
        "profile_payload": {
            "name": f"{brand or material_name} {name} — recommended", "technology": "FDM", "material": " · ".join(v for v in (brand, name) if v),
            "layer_height": None, "settings": settings, "notes": "Recommended starting values imported from SpoolmanDB. Validate on your own printer before relying on them.",
            "profile_origin": "Recommended", **meta,
        } if settings else None,
        "raw": raw,
    }


# ---------------- Open Resin Alliance ----------------

def _ora_tree(repo: str) -> list[str]:
    data = _fetch_json(f"ora-tree-{repo}", f"https://api.github.com/repos/Open-Resin-Alliance/{repo}/git/trees/main?recursive=1")
    return [x.get("path", "") for x in data.get("tree", []) if x.get("type") == "blob" and str(x.get("path", "")).startswith("materials/") and str(x.get("path", "")).endswith(".json")]


def _ora_printer_candidates(repo: str, printer: dict[str, Any]) -> list[str]:
    paths = _ora_tree(repo)
    man = _slug(str(printer.get("manufacturer") or ""))
    model = _slug(str(printer.get("model") or printer.get("name") or ""))
    model_toks = {t for t in model.split("-") if len(t) > 1}
    scored = []
    for p in paths:
        ps = _slug(p)
        score = 0
        if man and f"materials-{man}-" in ps: score += 20
        score += sum(4 for t in model_toks if t in ps)
        if model and model in ps: score += 30
        if score: scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    return [p for _, p in scored[:4]]


def _ora_file(repo: str, path: str) -> tuple[Any, str]:
    url = f"https://raw.githubusercontent.com/Open-Resin-Alliance/{repo}/main/{path}"
    data = _fetch_json("ora-file-" + hashlib.sha1(f"{repo}:{path}".encode()).hexdigest(), url)
    return data, f"https://github.com/Open-Resin-Alliance/{repo}/blob/main/{path}"


def _ora_settings(raw: dict[str, Any]) -> dict[str, Any]:
    # Prefer output-specific values when published because they normally contain
    # the printer-format-specific two-stage lift/retract settings.
    local = raw.get("localSettingsByOutput") or {}
    specific: dict[str, Any] = {}
    if isinstance(local, dict):
        for val in local.values():
            if isinstance(val, dict):
                specific = val
                break
    src = {**raw, **specific}
    out: dict[str, Any] = {}
    mapping = {
        "layerHeightMm": ("layer_height_mm", 1), "normalExposureSec": ("normal_exposure_s", 1),
        "bottomExposureSec": ("bottom_exposure_s", 1), "bottomLayerCount": ("bottom_layers", 1),
        "transitionLayerCount": ("transition_layers", 1), "liftDistanceMm": ("lift_distance_mm", 1),
        "liftDistance2Mm": ("lift_distance_2_mm", 1), "liftSpeedMmMin": ("lift_speed_mms", 1/60),
        "liftSpeed2MmMin": ("lift_speed_2_mms", 1/60), "retractSpeedMmMin": ("retract_speed_mms", 1/60),
        "retractSpeed2MmMin": ("retract_speed_2_mms", 1/60), "bottomLiftDistanceMm": ("bottom_lift_distance_mm", 1),
        "bottomLiftDistance2Mm": ("bottom_lift_distance_2_mm", 1), "bottomLiftSpeedMmMin": ("bottom_lift_speed_mms", 1/60),
        "bottomLiftSpeed2MmMin": ("bottom_lift_speed_2_mms", 1/60), "bottomRetractSpeedMmMin": ("bottom_retract_speed_mms", 1/60),
        "bottomRetractSpeed2MmMin": ("bottom_retract_speed_2_mms", 1/60), "lightOffDelaySec": ("light_off_delay_s", 1),
        "waitTimeBeforeCureSec": ("wait_before_cure_s", 1), "waitTimeAfterCureSec": ("wait_after_cure_s", 1),
        "waitTimeAfterLiftSec": ("wait_after_lift_s", 1), "projectorPwmPercent": ("projector_pwm_percent", 1),
        "minimumAaAlphaPercent": ("minimum_aa_alpha_percent", 1),
    }
    for sk, (dk, mul) in mapping.items():
        v = src.get(sk)
        if isinstance(v, (int, float)):
            out[dk] = round(float(v) * mul, 4)
    return out


def _ora_detail(repo: str, path: str, template_id: str, printer: dict[str, Any]) -> dict[str, Any]:
    arr, source_url = _ora_file(repo, path)
    entries = arr if isinstance(arr, list) else arr.get("materials", []) if isinstance(arr, dict) else []
    raw = next((x for x in entries if isinstance(x, dict) and str(x.get("templateId")) == template_id), None)
    if raw is None:
        raise KeyError("Resin profile not found in source")
    settings = _ora_settings(raw)
    brand = str(raw.get("brand") or _pretty_slug(repo.removeprefix("df-plugin-")))
    name = str(raw.get("name") or "Resin")
    family = str(raw.get("resinFamily") or "Resin")
    amount = float(raw.get("bottleCapacityMl") or 1000)
    key = f"{repo}|{path}|{template_id}"
    meta = _source_meta("openresin", key, source_url, raw)
    printer_name = str(printer.get("name") or printer.get("model") or "Resin printer")
    return {
        "provider": PROVIDER_INFO["openresin"], "key": key, "brand": brand, "name": name, "technology": "Resin", "kind": "Resin",
        "material": family, "color": "", "color_hex": "#8fd7c8", "package_amount": amount, "package_unit": "ml", "density": None,
        "settings": settings, "has_profile": bool(settings), "source_url": source_url,
        "source_price": raw.get("bottlePrice"), "source_currency": raw.get("currencyCode"), "valid_for_presets": raw.get("validForPresets") or [],
        "material_payload": {
            "name": f"{brand} {name}", "kind": "Resin", "material": family, "brand": brand, "color": "", "color_hex": "#8fd7c8",
            "initial_amount": amount, "remaining_amount": amount, "unit": "ml", **meta,
        },
        "profile_payload": {
            "name": f"{brand} {name} · {printer_name} — recommended", "technology": "MSLA / Resin", "material": f"{brand} {name}",
            "layer_height": settings.get("layer_height_mm"), "settings": settings,
            "notes": "Printer-specific starting profile imported from Open Resin Alliance / DragonFruit. Validate with a calibration print before treating it as proven.",
            "profile_origin": "Recommended", **meta,
        },
        "raw": raw,
    }


def providers() -> list[dict[str, Any]]:
    return list(PROVIDER_INFO.values())


def _search_artwork_fields(brand: Any, name: Any, material: Any, kind: str, color: Any = "") -> dict[str, Any]:
    official = _official_material(str(brand or ""), str(name or ""), str(material or ""), kind)
    allow_product_image = bool(official) and ("resin" in str(kind or "").casefold() or not str(color or "").strip())
    return {"has_image": allow_product_image, "official_product_url": (official or {}).get("url", "")}


def search(query: str, provider: str = "all", printer: dict[str, Any] | None = None, limit: int = 40) -> dict[str, Any]:
    q = (query or "").strip()
    if len(q) < 2:
        return {"results": [], "warnings": [], "query": q}
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    wanted = set(PROVIDER_INFO) if provider in {"", "all"} else {provider}

    if "manufacturer_resin" in wanted:
        try:
            products, reviewed_at = _manufacturer_resins()
            scored = []
            for item in products:
                score = _score_text(q, item.get("brand"), item.get("name"), item.get("family"))
                if score:
                    scored.append((score, item))
            scored.sort(key=lambda value: (-value[0], str(value[1].get("brand", "")).casefold(), str(value[1].get("name", "")).casefold()))
            for _, item in scored[:limit]:
                results.append({
                    "provider": "manufacturer_resin", "key": item["_key"], "brand": item.get("brand") or "",
                    "name": item.get("name") or "Resin", "material": item.get("family") or "Resin",
                    "color": "", "technology": "Resin", "kind": "Resin", "color_hex": "#8ed7ca",
                    "has_profile": False,
                    "summary": f"{item.get('family') or 'Resin'} · official product family · index reviewed {reviewed_at or 'locally'}",
                    "source_url": item.get("url") or PROVIDER_INFO["manufacturer_resin"]["homepage"],
                    **_search_artwork_fields(item.get("brand"), item.get("name"), item.get("family"), "Resin"),
                })
        except Exception as exc:
            warnings.append(f"Official Resin Catalogues: {exc}")

    if "spoolman" in wanted:
        try:
            scored = []
            for x in _spoolman_entries():
                s = _score_text(q, x.get("manufacturer"), x.get("name"), x.get("material"), x.get("color_name"))
                if s: scored.append((s, x))
            scored.sort(key=lambda z: (-z[0], str(z[1].get("manufacturer")), str(z[1].get("name"))))
            for _, x in scored[:limit]:
                results.append({"provider": "spoolman", "key": x["_key"], "brand": x.get("manufacturer") or "", "name": x.get("name") or "Filament",
                                "material": x.get("material") or "", "color": x.get("color_name") or "", "technology": "FDM", "kind": "Filament",
                                "color_hex": _colour_hex(x.get("color_hex")), "has_profile": bool(x.get("extruder_temp") or x.get("extruder_temp_range") or x.get("bed_temp") or x.get("bed_temp_range")),
                                "summary": " · ".join(str(v) for v in (x.get("weight") and f"{x.get('weight')}g", x.get("diameter") and f"{x.get('diameter')}mm", x.get("density") and f"ρ {x.get('density')}") if v),
                                "source_url": PROVIDER_INFO["spoolman"]["homepage"],
                                **_search_artwork_fields(x.get("manufacturer"), x.get("name"), x.get("material"), "Filament", x.get("color_name"))})
        except Exception as exc:
            warnings.append(f"SpoolmanDB: {exc}")

    if "openresin" in wanted:
        if not printer or str(printer.get("technology") or "").lower() not in {"resin", "msla / resin", "msla", "sla", "dlp"} and not re.search(r"resin|msla|sla|dlp", str(printer.get("technology") or ""), re.I):
            if provider == "openresin":
                warnings.append("Open Resin Alliance: choose one of your resin printers to search printer-specific starting profiles.")
        else:
            found_any = False
            for repo in ORA_MATERIAL_REPOS:
                try:
                    for p in _ora_printer_candidates(repo, printer):
                        arr, source_url = _ora_file(repo, p)
                        entries = arr if isinstance(arr, list) else arr.get("materials", []) if isinstance(arr, dict) else []
                        for raw in entries:
                            if not isinstance(raw, dict): continue
                            s = _score_text(q, raw.get("brand"), raw.get("name"), raw.get("resinFamily"))
                            if not s: continue
                            found_any = True
                            key = f"{repo}|{p}|{raw.get('templateId')}"
                            settings = _ora_settings(raw)
                            results.append({"provider": "openresin", "key": key, "brand": raw.get("brand") or "", "name": raw.get("name") or "Resin",
                                            "material": raw.get("resinFamily") or "Resin", "color": "", "technology": "Resin", "kind": "Resin",
                                            "color_hex": "#8fd7c8", "has_profile": bool(settings),
                                            "summary": f"{raw.get('layerHeightMm','—')}mm · {raw.get('normalExposureSec','—')}s exposure · {raw.get('bottleCapacityMl','—')}ml",
                                            "source_url": source_url,
                                            **_search_artwork_fields(raw.get("brand"), raw.get("name"), raw.get("resinFamily"), "Resin")})
                except Exception as exc:
                    warnings.append(f"Open Resin Alliance ({repo}): {exc}")
            if not found_any and not any(w.startswith("Open Resin Alliance") for w in warnings):
                warnings.append("Open Resin Alliance: no profile file matched this printer yet.")

    # Prefer specific printer profiles, then direct product records, then metadata-only hits.
    rank = {"openresin": 0, "manufacturer_resin": 1, "spoolman": 2}
    results.sort(key=lambda x: (rank.get(x["provider"], 9), str(x.get("brand", "")).casefold(), str(x.get("name", "")).casefold()))
    return {"results": results[:limit], "warnings": warnings, "query": q}


def detail(provider: str, key: str, printer: dict[str, Any] | None = None) -> dict[str, Any]:
    if provider == "manufacturer_resin":
        return _decorate_official_artwork(_manufacturer_resin_detail(key))
    if provider == "spoolman":
        for x in _spoolman_entries():
            if x.get("_key") == key:
                return _decorate_official_artwork(_spoolman_detail_from_entry(x))
        raise KeyError("SpoolmanDB item not found")
    if provider == "openresin":
        if not printer:
            raise KeyError("Choose a resin printer for this profile")
        parts = key.split("|", 2)
        if len(parts) != 3 or parts[0] not in ORA_MATERIAL_REPOS:
            raise KeyError("Invalid Open Resin Alliance item")
        return _decorate_official_artwork(_ora_detail(parts[0], parts[1], parts[2], printer))
    raise KeyError("Unknown material catalogue provider")


def image(provider: str, key: str, printer: dict[str, Any] | None = None) -> tuple[bytes, str]:
    item = detail(provider, key, printer)
    page_url = str(item.get("image_page_url") or "")
    if not page_url:
        raise KeyError("No official product artwork is available for this material")
    image_url = _og_image_url(page_url)
    cache_key = "official-image-" + hashlib.sha1(page_url.encode()).hexdigest()
    return _fetch_image(cache_key, image_url)


def image_from_official_page(page_url: str) -> tuple[bytes, str]:
    image_url = _og_image_url(page_url)
    cache_key = "official-image-" + hashlib.sha1(page_url.encode()).hexdigest()
    return _fetch_image(cache_key, image_url)
