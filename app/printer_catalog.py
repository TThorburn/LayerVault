from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx

_CACHE_DIR: Path | None = None
_IMAGE_DIR: Path | None = None
_FIXTURE_DIR: Path | None = None
_DRAGONFRUIT_ROOT: Path | None = None
_DRAGONFRUIT_INDEX: dict[str, dict[str, Any]] | None = None
_ORCA_PROFILE_ROOT: Path | None = None
_ORCA_LOCAL_INDEX: list[dict[str, Any]] | None = None
_UV_PROFILE_ROOT: Path | None = None

# UVtools contains a historical "Shuffle 16" slicing preset, but Phrozen's
# own legacy model list and specification archive do not identify a released
# printer by that name. Do not present a phantom machine with a guessed photo.
_UNVERIFIED_UV_PROFILE_STEMS = {"phrozen shuffle 16"}

PROVIDER_INFO = {
    "orca": {
        "id": "orca",
        "name": "OrcaSlicer printer profiles",
        "technology": "FDM",
        "description": "Community-maintained FDM machine profiles with printable area, height, nozzle variants and many printer cover images.",
        "license": "AGPL-3.0 upstream",
        "homepage": "https://github.com/OrcaSlicer/OrcaSlicer",
    },
    "uvtools": {
        "id": "uvtools",
        "name": "UVtools resin printer profiles",
        "technology": "Resin",
        "description": "Open resin-printer profiles with display resolution, physical screen dimensions and build height.",
        "license": "AGPL-3.0 upstream",
        "homepage": "https://github.com/sn4k3/UVtools",
    },
    "dragonfruit": {
        "id": "dragonfruit",
        "name": "DragonFruit resin printer library",
        "technology": "Resin",
        "description": "Bundled resin printer presets and artwork from the Open Resin Alliance DragonFruit plugins.",
        "license": "MIT plugin packs",
        "homepage": "https://github.com/Open-Resin-Alliance/DragonFruit",
    },
}

# Exact product artwork is used only when the retained open-source artwork
# does not contain the machine. ``image_url`` is reserved for retired models
# whose source page no longer exposes reliable Open Graph metadata. Keeping
# every model list exact avoids showing a visually similar but different unit.
OFFICIAL_PRINTER_PAGES: list[dict[str, Any]] = [
    # EPAX legacy and current resin families. Variant records intentionally
    # share artwork only where EPAX sold the same chassis with a different LCD.
    {"manufacturer": "epax", "models": ("dx1 pro",), "url": "https://epaxdental.com/products/dx1-9k-pro-dental-printer", "image_url": "https://epaxdental.com/cdn/shop/files/Front1_2048x2048.png?v=1767820470"},
    {"manufacturer": "epax", "models": ("dx10 pro 5k", "dx10 pro 8k"), "url": "https://epaxdental.com/products/dx10-pro-8k-dental-printer", "image_url": "https://epaxdental.com/cdn/shop/products/DX10-8KW-front_800x.jpg?v=1676570409"},
    {"manufacturer": "epax", "models": ("e6 mono",), "url": "https://www.manualslib.com/manual/2513667/Epax-E6-Series.html", "image_url": "https://static-data2.manualslib.com/product-images/4ee/2513667/epax-e6-series-3d-printers.jpg"},
    {"manufacturer": "epax", "models": ("e10 5k", "e10 8k", "e10 mono"), "url": "https://epax3d.com/pages/e10-spec", "image_url": "https://epax3d.com/cdn/shop/files/E10-14KWmainpicnew_1080x.png?v=1721147454"},
    {"manufacturer": "epax", "models": ("x1", "x1k 2k mono"), "url": "https://www.treatstock.com/machines/item/597-epax-x1", "image_url": "https://www.treatstock.com/static/uploads/printers/EPAX-3D-EPAX-X1.jpg"},
    {"manufacturer": "epax", "models": ("x1 4ks",), "url": "https://www.caddata3d.com/dental-drucker/130-epax-x1-4ks-66-mono-lcd-3d-printer.html", "image_url": "https://www.caddata3d.com/334-large_default/epax-x1-4ks-66-mono-lcd-3d-printer.jpg"},
    {"manufacturer": "epax", "models": ("x10", "x10 4k mono", "x10 5k"), "url": "https://www.treatstock.com/machines/item/569-epax-x10", "image_url": "https://www.treatstock.com/static/uploads/printers/EPAX3D-EPAX-X10.jpg"},
    {"manufacturer": "epax", "models": ("x133 4k mono", "x133 6k"), "url": "https://epax3d.com/collections/x133-and-x156-printers", "image_url": "https://epax3d.com/cdn/shop/products/selected-133-20201120_155546-small_7f20d26d-34fc-4e1d-b594-9139c08521c1_1080x.png?v=1647890182"},
    {"manufacturer": "epax", "models": ("x156 4k color",), "url": "https://epax3d.com/collections/x133-and-x156-printers", "image_url": "https://epax3d.com/cdn/shop/products/selected-156-20201120_121039small_3fff2b31-6e6d-4e35-b5e4-927b4b38a78d_1800x1800.jpg?v=1625772577"},
    # Longer publishes direct product photography for the Orange range. The
    # retired Orange 120 uses the archived exact-model comparison artwork.
    {"manufacturer": "longer", "models": ("orange 10",), "url": "https://www.longer3d.com/products/orange-10-resin-3d-printer", "image_url": "https://www.longer3d.com/cdn/shop/files/orange-10-resin-3d-printer-962663.jpg?v=1719819289"},
    {"manufacturer": "longer", "models": ("orange 30",), "url": "https://www.longer3d.com/products/orange-30-resin-3d-printer", "image_url": "https://www.longer3d.com/cdn/shop/products/LongerOrange303DPrinter_7.jpg?v=1613075912"},
    {"manufacturer": "longer", "models": ("orange 4k",), "url": "https://www.longer3d.com/products/orange-4k-resin-3d-printer", "image_url": "https://www.longer3d.com/cdn/shop/files/orange-4k-resin-3d-printer-604766.jpg?v=1719799193"},
    {"manufacturer": "longer", "models": ("orange 120",), "url": "https://www.lesimprimantes3d.fr/comparateur/imprimante3d/longer/orange-120/", "image_url": "https://www.lesimprimantes3d.fr/wp-content/uploads/2020/11/longer-orange-120.jpg"},
    # Phrozen's retired Shuffle/Sonic models are retained from exact reseller
    # archives; current models continue to use the manufacturer product pages.
    {"manufacturer": "phrozen", "models": ("shuffle",), "url": "https://www.3dprintersbay.com/phrozen-shuffle", "image_url": "https://d1n63dwz6yw5wy.cloudfront.net/cache/catalog/phrozen/phrozen-shuffle-disp-2-750x930.jpg"},
    {"manufacturer": "phrozen", "models": ("shuffle 4k",), "url": "https://www.3dprintersbay.com/phrozen-shuffle-4k", "image_url": "https://www.3dprintersbay.com/image/cache/catalog/phrozen-shuffle-4k/phrozen-shuffle-4k-1-750x930.jpg"},
    {"manufacturer": "phrozen", "models": ("shuffle lite",), "url": "https://www.3dprintersbay.com/phrozen-shuffle-lite", "image_url": "https://www.3dprintersbay.com/image/cache/catalog/phrozen/phrozen-shuffle-lite-8-750x930.jpg"},
    {"manufacturer": "phrozen", "models": ("shuffle xl",), "url": "https://www.3dprinters-shop.com/en/resin-3d-printers/450-phrozen-shuffle-xl.html", "image_url": "https://www.3dprinters-shop.com/1695-large_default/phrozen-shuffle-xl.jpg"},
    {"manufacturer": "phrozen", "models": ("shuffle xl lite",), "url": "https://www.3dprinters-shop.com/en/phrozen/511-phrozen-shuffle-xl-lite.html", "image_url": "https://www.3dprinters-shop.com/1949-medium_default/phrozen-shuffle-xl-lite.jpg"},
    {"manufacturer": "phrozen", "models": ("sonic",), "url": "https://www.3dprintersbay.com/phrozen-sonic", "image_url": "https://www.3dprintersbay.com/image/cache/catalog/sonic/Phrozen-Sonic-01-750x930.jpg"},
    {"manufacturer": "phrozen", "models": ("sonic 4k",), "url": "https://www.3dprintersbay.com/phrozen-sonic-4k", "image_url": "https://www.3dprintersbay.com/image/cache/catalog/sonic-4k/phrozen-sonic-4k-2-750x930.jpg"},
    {"manufacturer": "phrozen", "models": ("sonic mighty 4k",), "url": "https://www.3dprintersbay.com/phrozen-sonic-mighty", "image_url": "https://d1n63dwz6yw5wy.cloudfront.net/cache/catalog/sonic-mighty/phrozen-sonic-mighty-1-650x800.jpg"},
    {"manufacturer": "phrozen", "models": ("sonic mega 8k",), "url": "https://www.3dbazaar.in/product/phrozen-sonic-mega-8k-resin-3d-printer/", "image_url": "https://www.3dbazaar.in/wp-content/uploads/2022/09/Phrozen-Mega-8K-3D-Bazaar-01.png"},
    {"manufacturer": "phrozen", "models": ("sonic mini",), "url": "https://us.phrozen3d.com/products/sonic-mini", "image_url": "https://us.phrozen3d.com/cdn/shop/products/SonicMini-4_7aa88d70-54a2-4a31-8aae-6d863dc7da3b.png?v=1696313346&width=1214"},
    {"manufacturer": "phrozen", "models": ("sonic mini 4k",), "url": "https://quanton3d.com.br/parametrosdeimpressao/", "image_url": "https://d1a9qnv764bsoo.cloudfront.net/stores/006/404/136/rte/phrozen-mini-4k.png"},
    {"manufacturer": "phrozen", "models": ("transform",), "url": "https://3dprinteruniverse.com/products/phrozen-transform-large-lcd-msla-3d-printer", "image_url": "https://cdn.shopify.com/s/files/1/1298/7149/products/2019-10-24_05.44.57_PM_large.png?v=1579645327"},
    # Qidi's resin range predates the current FDM catalogue, so exact archived
    # product photography is retained alongside the manufacturer profile data.
    {"manufacturer": "qidi", "models": ("i box mono",), "url": "https://eu.qidi3d.com/collections/3d-printers", "image_url": "https://eu.qidi3d.com/cdn/shop/products/2.jpg?v=1703817126"},
    {"manufacturer": "qidi", "models": ("s box",), "url": "https://www.toolots.com/qdsbox.html", "image_url": "https://content.toolots.com/media/catalog/product/y/3/y3leikert_1806381.jpg"},
    {"manufacturer": "qidi", "models": ("shadow5 5",), "url": "https://www.treatstock.com/machines/item/572-shadow-55-s", "image_url": "https://www.treatstock.com/static/uploads/printers/Qidi-Tech-Shadow-5-5S.jpg"},
    {"manufacturer": "qidi", "models": ("shadow6 0 pro",), "url": "https://3d-drucker-portal.de/produkt/qidi-tech-shadow-6-0-pro-kaufen/", "image_url": "https://3d-drucker-portal.de/wp-content/uploads/2020/06/qidi-tech-shadow-6-0-pro-1-pc.jpg"},
    {"manufacturer": "phrozen", "models": ("sonic mini 8k",), "url": "https://us.phrozen3d.com/products/sonic-mini-8k"},
    {"manufacturer": "phrozen", "models": ("sonic mini 8k s",), "url": "https://us.phrozen3d.com/products/sonic-mini-8k-s"},
    {"manufacturer": "phrozen", "models": ("sonic mighty 8k",), "url": "https://us.phrozen3d.com/products/sonic-mighty-8k"},
    {"manufacturer": "phrozen", "models": ("sonic mighty revo",), "url": "https://us.phrozen3d.com/products/sonic-mighty-revo"},
    {"manufacturer": "creality", "models": ("halot lite", "halot lite cl 89l"), "url": "https://www.creality.com/products/creality-halot-lite-resin-3d-printer"},
    {"manufacturer": "creality", "models": ("halot mage", "halot mage cl 103l"), "url": "https://www.creality.com/products/halot-mage"},
    {"manufacturer": "creality", "models": ("halot mage pro", "halot mage pro cl 103"), "url": "https://store.creality.com/products/halot-mage-pro-8k-resin-3d-printer"},
    {"manufacturer": "creality", "models": ("halot max", "halot max cl 133"), "url": "https://store.creality.com/eu/products/halot-max-resin-3d-printer-pre-sale"},
    {"manufacturer": "creality", "models": ("halot one", "halot one cl 60"), "url": "https://www.creality.com/products/halot-one-resin-3d-printer"},
    {"manufacturer": "creality", "models": ("halot one plus", "halot one plus cl 79"), "url": "https://www.creality.com/ae/products/halot-one-plus-3d-printer"},
    {"manufacturer": "creality", "models": ("halot one pro", "halot one pro cl 70"), "url": "https://www.creality.com/products/halot-one-pro-3d-printer"},
    {"manufacturer": "creality", "models": ("halot ray", "halot ray cl925"), "url": "https://www.creality.com/products/halot-ray-3d-printer"},
    {"manufacturer": "creality", "models": ("halot sky", "halot sky cl 89", "halot sky plus", "halot sky plus cl 92"), "url": "https://www.creality.com/products/halot-sky-3d-printer"},
    {"manufacturer": "creality", "models": ("ld 002h",), "url": "https://www.creality.com/jp/blog/ld-002h-vs-ld-002r-what-are-the-improvements-in-ld-002h"},
    {"manufacturer": "creality", "models": ("ld 002r",), "url": "https://www.creality3dofficial.com/en/products/ld-002r-lcd-resin-3d-printer"},
    {"manufacturer": "creality", "models": ("ld 006",), "url": "https://www.creality.com/products/creality-ld-006-resin-3d-printer"},
    {"manufacturer": "elegoo", "models": ("mars",), "url": "https://www.elegoo.com/products/elegoo-mars-lcd-3d-printer"},
    {"manufacturer": "elegoo", "models": ("mars c",), "url": "https://us.elegoo.com/products/elegoo-mars-c-lcd-3d-printer"},
    {"manufacturer": "elegoo", "models": ("mars 2",), "url": "https://www.elegoo.com/products/elegoo-mars-2-mono-lcd-3d-printer"},
    {"manufacturer": "elegoo", "models": ("saturn",), "url": "https://www.elegoo.com/products/elegoo-saturn-4k-mono-lcd-3d-printer"},
    {"manufacturer": "elegoo", "models": ("saturn 8k",), "url": "https://www.elegoo.com/en-gb/products/elegoo-saturn-8k-msla-10inch-monochrome-lcd-resin-3d-printer"},
    {"manufacturer": "elegoo", "models": ("saturn s",), "url": "https://www.elegoo.com/en-gb/products/elegoo-saturn-s-msla-9-1-4k-mono-lcd-3d-printer"},
    {"manufacturer": "uniformation", "models": ("gktwo", "gk two"), "url": "https://uniformation3d.com/products/uniformation-gktwo-10-3-8k-resin-printer"},
    {"manufacturer": "nova3d", "models": ("bene4 mono",), "url": "https://store.nova3dp.com/pages/video-support", "image_url": "https://store.nova3dp.com/cdn/shop/files/202009031140580329.jpg?v=1681543590&width=580"},
    {"manufacturer": "nova3d", "models": ("bene4",), "url": "https://store.nova3dp.com/pages/video-support", "image_url": "https://store.nova3dp.com/cdn/shop/files/202301291104022524_cb1c3479-5c84-4b8c-993f-6f917dabd531.jpg?v=1681551764&width=580"},
    {"manufacturer": "nova3d", "models": ("bene5",), "url": "https://www.alibaba.com/product-introduction/NOVA3D-Factory-Wholesale-Dental-3d-Printer_1601049466838.html", "image_url": "https://sc04.alicdn.com/kf/H1824cfc9591f4734922ccdcbae302d7bO.jpg"},
    {"manufacturer": "nova3d", "models": ("bene6",), "url": "https://store.nova3dp.com/pages/video-support", "image_url": "https://store.nova3dp.com/cdn/shop/files/2_2d561004-a1cf-4f29-b083-41c289eb02fe.jpg?v=1681543352&width=580"},
    {"manufacturer": "nova3d", "models": ("elfin",), "url": "https://www.3dprintersbay.com/nova3d-elfin", "image_url": "https://d1n63dwz6yw5wy.cloudfront.net/cache/catalog/elfin/nova3d-elfin-2-750x930.jpg"},
    {"manufacturer": "nova3d", "models": ("elfin2",), "url": "https://incraft3d.ru/files/docs/B1E6EMKnt5S.pdf", "image_url": "printer-art://nova3d-elfin2.png"},
    {"manufacturer": "nova3d", "models": ("elfin2 mono se",), "url": "https://store.nova3dp.com/pages/video-support", "image_url": "https://store.nova3dp.com/cdn/shop/files/Hdf562c6f077e4c4884c9f243aa271015V.jpg?v=1681551789&width=580"},
    {"manufacturer": "nova3d", "models": ("elfin3 mini",), "url": "https://latestintech.com/nova3d-elfin-3-mini-resin-printer-review/", "image_url": "https://latestintech.com/wp-content/uploads/2021/09/Nova3D-Elfin3-Mini-Review-4.jpg"},
    {"manufacturer": "nova3d", "models": ("whale2",), "url": "https://store.nova3dp.com/pages/video-support", "image_url": "https://store.nova3dp.com/cdn/shop/files/202301291104022524_ce81007f-acbe-42d9-a3ba-e0920019dde4.jpg?v=1681543524&width=580"},
    {"manufacturer": "nova3d", "models": ("whale",), "url": "https://voxeldance.com/mobile/zcddyj.html", "image_url": "https://voxeldance.com/mobile/img/31405563.png"},
    {"manufacturer": "nova3d", "models": ("whale3 pro",), "url": "https://store.nova3dp.com/pages/download", "image_url": "https://store.nova3dp.com/cdn/shop/files/202301291104022524_afd9ded6-14bb-462f-bf76-a4b2082c9e08.jpg?v=1681543231&width=580"},
    {"manufacturer": "wanhao", "models": ("cgr mini mono",), "url": "https://wanhao.store/products/cgr-mini-lifting-platform-components", "image_url": "https://cdn.shopifycdn.net/s/files/1/1335/8485/files/858A0683_480x480.jpg?v=1621675764"},
    {"manufacturer": "wanhao", "models": ("cgr mono",), "url": "https://wanhao.store/products/wanahao-resin-3d-printer-cgr-use-4k-8-9inch-lcd-with-high-resolution", "image_url": "https://cdn.shopify.com/s/files/1/1335/8485/products/858A0689.jpg?v=1662705170"},
    {"manufacturer": "wanhao", "models": ("d7",), "url": "https://wanhao.store/fr/products/wanaho-duplicator-d7-v1-5", "image_url": "https://cdn.shopify.com/s/files/1/1335/8485/products/DSC_0558_1.png?v=1662717867"},
    {"manufacturer": "wanhao", "models": ("d8",), "url": "https://wanhao.store/products/d8", "image_url": "https://cdn.shopify.com/s/files/1/1335/8485/products/DSC_00152.jpg?v=1662717801"},
    {"manufacturer": "prusa", "models": ("sl1",), "url": "https://help.prusa3d.com/article/original-prusa-sl1-vs-sl1s-speed_233097", "image_url": "https://cdn.help.prusa3d.com/wp-content/uploads/2021/11/DSC_3248-copy.jpg"},
    {"manufacturer": "prusa", "models": ("sl1s speed",), "url": "https://cdn.prusa3d.com/en/product/original-prusa-sl1s-speed-3d-printer/", "image_url": "https://cdn.prusa3d.com/cdn-cgi/image/width%3D1024%2Cformat%3Dauto%2Cquality%3D85/content/images/product/2609db0b-925b-4b71-a494-11b462cc8119.jpg"},
]

_OFFICIAL_PRINTER_HOSTS = {
    "store.anycubic.com", "us.phrozen3d.com", "store.creality.com", "www.creality.com",
    "www.creality3dofficial.com", "www.elegoo.com", "us.elegoo.com", "uniformation3d.com",
    "store.nova3dp.com", "www.nova3dp.com", "nova3dp.com", "wanhao.store",
    "help.prusa3d.com", "cdn.help.prusa3d.com", "cdn.prusa3d.com",
    "epax3d.com", "epaxdental.com", "www.longer3d.com", "us.phrozen3d.com",
    "eu.qidi3d.com",
}
_OFFICIAL_IMAGE_HOSTS = _OFFICIAL_PRINTER_HOSTS | {
    "cdn.shopify.com", "cdn.shopifycdn.net", "images.ctfassets.net",
    "d1n63dwz6yw5wy.cloudfront.net", "latestintech.com",
    "voxeldance.com", "sc04.alicdn.com", "static-data2.manualslib.com",
    "www.treatstock.com", "www.caddata3d.com", "www.lesimprimantes3d.fr",
    "www.3dprintersbay.com", "www.3dprinters-shop.com", "www.3dbazaar.in",
    "d1a9qnv764bsoo.cloudfront.net", "content.toolots.com", "3d-drucker-portal.de",
}


def configure(data_dir: Path) -> None:
    global _CACHE_DIR, _IMAGE_DIR, _FIXTURE_DIR, _DRAGONFRUIT_ROOT, _DRAGONFRUIT_INDEX, _ORCA_PROFILE_ROOT, _ORCA_LOCAL_INDEX, _UV_PROFILE_ROOT
    _CACHE_DIR = Path(data_dir) / "catalog-cache" / "printers"
    _IMAGE_DIR = Path(data_dir) / "catalog-cache" / "printer-images"
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    fixture = os.getenv("PRINTER_CATALOG_FIXTURE_DIR", os.getenv("CATALOG_FIXTURE_DIR", "")).strip()
    _FIXTURE_DIR = Path(fixture) if fixture else None
    bundled = Path(__file__).resolve().parent.parent / "third_party" / "dragonfruit" / "plugins"
    _DRAGONFRUIT_ROOT = Path(os.getenv("DRAGONFRUIT_PRINTER_ROOT", str(bundled))).resolve()
    _DRAGONFRUIT_INDEX = None
    orca_bundled = Path(__file__).resolve().parent.parent / "third_party" / "printer-artwork" / "orcaslicer" / "profiles"
    _ORCA_PROFILE_ROOT = Path(os.getenv("ORCA_PRINTER_ART_ROOT", str(orca_bundled))).resolve()
    _ORCA_LOCAL_INDEX = None
    uv_bundled = Path(__file__).resolve().parent.parent / "third_party" / "uvtools" / "PrusaSlicer" / "printer"
    _UV_PROFILE_ROOT = Path(os.getenv("UVTOOLS_PRINTER_PROFILE_ROOT", str(uv_bundled))).resolve()


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", key)[:180]


def _fixture_text(key: str) -> str | None:
    if not _FIXTURE_DIR:
        return None
    for suffix in ("", ".json", ".ini", ".txt"):
        p = _FIXTURE_DIR / f"{_safe_key(key)}{suffix}"
        if p.exists():
            return p.read_text(encoding="utf-8")
    return None


def _fixture_bytes(key: str) -> bytes | None:
    if not _FIXTURE_DIR:
        return None
    for suffix in (".png", ".jpg", ".jpeg", ".webp", ".bin"):
        p = _FIXTURE_DIR / f"{_safe_key(key)}{suffix}"
        if p.exists():
            return p.read_bytes()
    return None


def _fetch_text(key: str, url: str, ttl: int = 24 * 3600) -> str:
    fixture = _fixture_text(key)
    if fixture is not None:
        return fixture
    if _CACHE_DIR is None:
        raise RuntimeError("Printer catalogue not configured")
    cache = _CACHE_DIR / f"{_safe_key(key)}.cache"
    if cache.exists() and time.time() - cache.stat().st_mtime < ttl:
        return cache.read_text(encoding="utf-8")
    headers = {"User-Agent": "LayerVault-printer-catalog/0.2.1", "Accept": "application/json,text/plain,*/*"}
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
        raise RuntimeError(f"Could not reach printer source: {exc}") from exc


def _fetch_json(key: str, url: str, ttl: int = 24 * 3600) -> Any:
    return json.loads(_fetch_text(key, url, ttl))


def _fetch_image(key: str, url: str, ttl: int = 30 * 24 * 3600) -> tuple[bytes, str]:
    fixture = _fixture_bytes(key)
    if fixture is not None:
        return fixture, "image/png"
    if _IMAGE_DIR is None:
        raise RuntimeError("Printer catalogue not configured")
    ext = Path(url.split("?", 1)[0]).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".img"
    cache = _IMAGE_DIR / f"{hashlib.sha1(key.encode()).hexdigest()}{ext}"
    meta = cache.with_suffix(cache.suffix + ".json")
    if cache.exists() and time.time() - cache.stat().st_mtime < ttl:
        ctype = "image/png"
        if meta.exists():
            try: ctype = json.loads(meta.read_text()).get("content_type") or ctype
            except Exception: pass
        return cache.read_bytes(), ctype
    source_host = (urlparse(url).hostname or "").casefold()
    if not url.startswith("https://raw.githubusercontent.com/") and source_host not in _OFFICIAL_IMAGE_HOSTS:
        raise RuntimeError("Printer image source is not on an approved upstream host")
    headers = {"User-Agent": "LayerVault-printer-catalog/0.2.1", "Accept": "image/*"}
    try:
        with httpx.Client(timeout=25.0, follow_redirects=True, headers=headers) as client:
            r = client.get(url)
            r.raise_for_status()
            final_host = (r.url.host or "").casefold()
            if not str(r.url).startswith("https://raw.githubusercontent.com/") and final_host not in _OFFICIAL_IMAGE_HOSTS:
                raise RuntimeError("Printer artwork redirected to an unapproved host")
            data = r.content
            ctype = r.headers.get("content-type", "").split(";", 1)[0] or mimetypes.guess_type(url)[0] or "image/png"
        if not ctype.startswith("image/") or len(data) > 8 * 1024 * 1024:
            raise RuntimeError("Unexpected printer image response")
        tmp = cache.with_suffix(cache.suffix + ".tmp")
        tmp.write_bytes(data); tmp.replace(cache)
        meta.write_text(json.dumps({"content_type": ctype, "source": url}))
        return data, ctype
    except Exception as exc:
        if cache.exists():
            return cache.read_bytes(), (mimetypes.guess_type(cache.name)[0] or "image/png")
        raise RuntimeError(f"Could not fetch printer image: {exc}") from exc


def _score(query: str, *parts: Any) -> int:
    q = (query or "").strip().casefold()
    if not q: return 1
    toks = [t for t in re.split(r"\s+", q) if t]
    hay = " ".join(str(p or "") for p in parts).casefold()
    if not all(t in hay for t in toks): return 0
    score = 10 + (10 if q in hay else 0)
    for p in parts:
        s = str(p or "").casefold()
        if s == q: score += 25
        elif s.startswith(q): score += 8
    return score


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


_MODEL_ALIASES = {
    ("anycubic", "photonmonox6k"): "photonmonox6km3plus",
    ("anycubic", "photonm3plus"): "photonmonox6km3plus",
    ("anycubic", "photonmonox6kphotonm3pluspwmb"): "photonmonox6km3plus",
    ("anycubic", "photonmonox6km3plus"): "photonmonox6km3plus",
    ("elegoo", "saturn4ultra12k"): "saturn4ultra",
}


def _printer_parts(manufacturer: str, model: str) -> tuple[str, str]:
    maker = _norm(manufacturer)
    machine = _norm(model)
    if maker and machine.startswith(maker) and len(machine) > len(maker):
        machine = machine[len(maker):]
    return maker, _MODEL_ALIASES.get((maker, machine), machine)


def _official_printer_artwork(manufacturer: str, model: str) -> dict[str, Any] | None:
    maker = re.sub(r"[^a-z0-9]+", " ", (manufacturer or "").casefold()).strip()
    machine = re.sub(r"[^a-z0-9]+", " ", (model or "").casefold()).strip()
    if maker and machine.startswith(maker + " "):
        machine = machine[len(maker):].strip()
    # UVtools ships the Prusa brand as part of the model stem rather than as
    # the manufacturer. Correct that source quirk before exact matching.
    if maker == "uvtools" and machine.startswith("prusa "):
        maker, machine = "prusa", machine.removeprefix("prusa ").strip()
    for record in OFFICIAL_PRINTER_PAGES:
        if maker == record["manufacturer"] and machine in record["models"]:
            return record
    return None


def _official_printer_page(manufacturer: str, model: str) -> str:
    artwork = _official_printer_artwork(manufacturer, model)
    return str(artwork["url"]) if artwork else ""


def _is_direct_image_url(url: str) -> bool:
    return Path(urlparse(url).path).suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}


def _bundled_printer_art(url: str) -> Path | None:
    if not url.startswith("printer-art://"):
        return None
    root = (Path(__file__).resolve().parent.parent / "third_party" / "printer-artwork" / "resin-supplement").resolve()
    candidate = (root / url.removeprefix("printer-art://")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() and candidate.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"} else None


def _official_page_image(page_url: str) -> tuple[bytes, str]:
    parsed = urlparse(page_url)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in _OFFICIAL_PRINTER_HOSTS:
        raise RuntimeError("Printer product page is not an approved manufacturer source")
    page = _fetch_text("printer-official-page-" + hashlib.sha1(page_url.encode()).hexdigest(), page_url, 7 * 24 * 3600)
    patterns = (
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, page, re.I)
        if match:
            image_url = urljoin(page_url, html.unescape(match.group(1).strip()))
            return _fetch_image("official-printer-" + hashlib.sha1(page_url.encode()).hexdigest(), image_url)
    raise RuntimeError("Official printer page did not publish a product image")


def _float(v: Any) -> float | None:
    try:
        if isinstance(v, list): v = v[0] if v else None
        return float(v) if v not in (None, "") else None
    except Exception:
        return None


def _int(v: Any) -> int | None:
    f = _float(v)
    return int(f) if f is not None else None


# ---------------- DragonFruit / bundled resin presets ----------------

def _dragonfruit_index() -> dict[str, dict[str, Any]]:
    global _DRAGONFRUIT_INDEX
    if _DRAGONFRUIT_INDEX is not None:
        return _DRAGONFRUIT_INDEX
    index: dict[str, dict[str, Any]] = {}
    root = _DRAGONFRUIT_ROOT
    if root and root.is_dir():
        for profile_path in root.glob("*/printers/*.json"):
            try:
                payload = json.loads(profile_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, list):
                continue
            plugin = profile_path.relative_to(root).parts[0]
            for raw in payload:
                if not isinstance(raw, dict) or not raw.get("presetId") or not raw.get("imageAssetPath"):
                    continue
                asset = (profile_path.parent / str(raw["imageAssetPath"])).resolve()
                try:
                    asset.relative_to(profile_path.parent.resolve())
                except ValueError:
                    continue
                if not asset.is_file() or asset.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    continue
                key = f"{plugin}:{raw['presetId']}"
                index[key] = {"raw": raw, "asset": asset, "profile": profile_path, "plugin": plugin}
    _DRAGONFRUIT_INDEX = index
    return index


def _dragonfruit_detail(key: str) -> dict[str, Any]:
    record = _dragonfruit_index().get(key)
    if not record:
        raise KeyError("DragonFruit printer preset not found")
    raw = record["raw"]
    volume = raw.get("buildVolumeMm") or {}
    pixels = raw.get("pixelSize") or {}
    display = raw.get("display") or {}
    relative = record["profile"].relative_to(_DRAGONFRUIT_ROOT).as_posix() if _DRAGONFRUIT_ROOT else ""
    source_url = "https://github.com/Open-Resin-Alliance/DragonFruit/blob/main/plugins/" + quote(relative, safe="/")
    return {
        "provider": PROVIDER_INFO["dragonfruit"], "provider_id": "dragonfruit", "key": key,
        "manufacturer": raw.get("manufacturer") or record["plugin"].title(), "model": raw.get("name") or raw.get("presetId"),
        "name": raw.get("name") or raw.get("presetId"), "technology": "MSLA / Resin",
        "build_x": _float(volume.get("width")), "build_y": _float(volume.get("depth")), "build_z": _float(volume.get("height")),
        "nozzle_mm": None, "nozzle_options": [], "resolution_x": _int(display.get("resolutionX")),
        "resolution_y": _int(display.get("resolutionY")), "xy_resolution_x_um": _float(pixels.get("x")),
        "xy_resolution_y_um": _float(pixels.get("y")), "screen_width_mm": _float(volume.get("width")),
        "screen_height_mm": _float(volume.get("depth")), "image_url": f"dragonfruit://{key}",
        "source_url": source_url, "source_license": "MIT (Open Resin Alliance printer plugin)",
        "capabilities": {
            "family": raw.get("family"), "anti_aliasing": raw.get("antiAliasing"), "has_camera": raw.get("hasCamera"),
            "network_support": raw.get("networkSupport"), "output_format": display.get("outputFormat"),
            "format_version": display.get("formatVersion"), "settings_mode": display.get("settingsMode"),
            "bit_depth": raw.get("bitDepth"),
        },
        "source_snapshot": raw,
    }


def _search_dragonfruit(q: str, limit: int) -> list[dict[str, Any]]:
    scored: list[tuple[int, str]] = []
    for key, record in _dragonfruit_index().items():
        raw = record["raw"]
        score = _score(q, raw.get("manufacturer"), raw.get("name"), raw.get("family"), raw.get("presetId"))
        if score:
            scored.append((score, key))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [_dragonfruit_detail(key) for _, key in scored[:limit]]


def local_image_for_printer(manufacturer: str, model: str) -> dict[str, Any] | None:
    target_maker, model_target = _printer_parts(manufacturer, model)
    if not model_target:
        return None
    for key, record in _dragonfruit_index().items():
        raw = record["raw"]
        candidate_maker, candidate_model = _printer_parts(str(raw.get("manufacturer") or ""), str(raw.get("name") or ""))
        if candidate_maker == target_maker and candidate_model == model_target:
            return _dragonfruit_detail(key)
    # FDM artwork is retained as a small, licensed subset of OrcaSlicer's
    # machine profile library; the slicer runtime itself is not required.
    best: tuple[int, str] | None = None
    target = _norm(f"{manufacturer} {model}")
    for record in _orca_local_index():
        candidate_model = _norm(record["model"])
        candidate_maker = _norm(record["manufacturer"])
        candidate_full = _norm(f'{record["manufacturer"]} {record["model"]}')
        score = 0
        if candidate_full == target: score = 120
        elif candidate_model == model_target: score = 100
        elif target and (target in candidate_full or candidate_full in target): score = 88
        elif min(len(candidate_model), len(model_target)) >= 5 and (candidate_model in model_target or model_target in candidate_model): score = 62
        if target_maker and (target_maker in candidate_full or candidate_maker in target): score += 18
        if score and (best is None or score > best[0]): best = (score, record["key"])
    if best and best[0] >= 80:
        detail = _orca_detail(best[1], _orca_tree())
        if detail.get("image_url"): return detail
    official_artwork = _official_printer_artwork(manufacturer, model)
    if official_artwork:
        source_page = str(official_artwork["url"])
        return {
            "provider_id": "official", "key": f"{target_maker}:{model_target}",
            "manufacturer": manufacturer, "model": model, "name": model,
            "technology": "MSLA / Resin", "image_url": str(official_artwork.get("image_url") or source_page),
            "source_url": source_page, "source_license": "Product artwork; source page linked",
        }
    return None


def _area_dimensions(points: Any) -> tuple[float | None, float | None]:
    if not isinstance(points, list): return None, None
    xs: list[float] = []; ys: list[float] = []
    for p in points:
        m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*[x,]\s*(-?\d+(?:\.\d+)?)\s*$", str(p))
        if m:
            xs.append(float(m.group(1))); ys.append(float(m.group(2)))
    if not xs or not ys: return None, None
    return round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3)


# ---------------- OrcaSlicer / FDM ----------------

def _orca_local_path(path: str) -> Path | None:
    root = _ORCA_PROFILE_ROOT
    prefix = "resources/profiles/"
    if not root or not root.is_dir() or not path.startswith(prefix) or ".." in path:
        return None
    candidate = (root / path[len(prefix):]).resolve()
    try: candidate.relative_to(root.resolve())
    except ValueError: return None
    return candidate if candidate.is_file() else None

def _orca_tree() -> list[str]:
    if _ORCA_PROFILE_ROOT and _ORCA_PROFILE_ROOT.is_dir():
        return ["resources/profiles/" + path.relative_to(_ORCA_PROFILE_ROOT).as_posix() for path in _ORCA_PROFILE_ROOT.rglob("*") if path.is_file()]
    data = _fetch_json("orca-tree", "https://api.github.com/repos/OrcaSlicer/OrcaSlicer/git/trees/main?recursive=1", 12 * 3600)
    return [x.get("path", "") for x in data.get("tree", []) if x.get("type") == "blob"]


def _orca_file(path: str) -> dict[str, Any]:
    if ".." in path or not path.startswith("resources/profiles/") or not path.endswith(".json"):
        raise KeyError("Invalid OrcaSlicer profile path")
    local = _orca_local_path(path)
    if local:
        return json.loads(local.read_text(encoding="utf-8"))
    url = "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/main/" + quote(path, safe="/")
    return _fetch_json("orca-file-" + hashlib.sha1(path.encode()).hexdigest(), url)


def _orca_cover(model: str, profile_path: str, tree: list[str] | None = None) -> str:
    tree = tree or _orca_tree()
    # Machine variants live in ``<vendor>/machine`` while Orca's artwork is
    # stored at the vendor root. Keep the lookup local to that vendor so
    # similarly named printers from different manufacturers cannot collide.
    parts = profile_path.split("/")
    folder = "/".join(parts[:3]) + "/" if len(parts) > 3 else profile_path.rsplit("/", 1)[0] + "/"
    target = _norm(model)
    candidates = [p for p in tree if p.startswith(folder) and p.lower().endswith(("_cover.png", "_cover.jpg", "_cover.jpeg", "_cover.webp"))]
    exact = next((p for p in candidates if _norm(Path(p).stem.replace("_cover", "")) == target), None)
    if not exact:
        exact = next((p for p in candidates if target and (target in _norm(Path(p).stem) or _norm(Path(p).stem.replace("_cover", "")) in target)), None)
    if not exact: return ""
    if _orca_local_path(exact): return "orca-local://" + exact
    return "https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/main/" + quote(exact, safe="/")


def _orca_local_index() -> list[dict[str, Any]]:
    global _ORCA_LOCAL_INDEX
    if _ORCA_LOCAL_INDEX is not None: return _ORCA_LOCAL_INDEX
    records: list[dict[str, Any]] = []
    if _ORCA_PROFILE_ROOT and _ORCA_PROFILE_ROOT.is_dir():
        tree = _orca_tree()
        for profile in _ORCA_PROFILE_ROOT.glob("*/machine/*.json"):
            if profile.stem.casefold().startswith("fdm_"):
                continue
            try: raw = json.loads(profile.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError): continue
            if raw.get("type") != "machine": continue
            key = "resources/profiles/" + profile.relative_to(_ORCA_PROFILE_ROOT).as_posix()
            model = str(raw.get("printer_model") or raw.get("name") or profile.stem)
            image_url = _orca_cover(model, key, tree)
            if image_url:
                records.append({"key": key, "model": model, "manufacturer": profile.relative_to(_ORCA_PROFILE_ROOT).parts[0]})
    _ORCA_LOCAL_INDEX = records
    return records


def _orca_detail(path: str, tree: list[str] | None = None) -> dict[str, Any]:
    if Path(path).stem.casefold().startswith("fdm_"):
        raise KeyError("OrcaSlicer inheritance profile is not an installable printer")
    raw = _orca_file(path)
    if raw.get("type") != "machine":
        raise KeyError("OrcaSlicer profile is not an installable machine variant")
    model = str(raw.get("printer_model") or raw.get("name") or Path(path).stem)
    vendor = path.split("/")[2] if len(path.split("/")) > 3 else ""
    bx, by = _area_dimensions(raw.get("printable_area") or raw.get("bed_shape"))
    bz = _float(raw.get("printable_height") or raw.get("max_print_height"))
    nozzle_values = raw.get("nozzle_diameter") or []
    if not isinstance(nozzle_values, list): nozzle_values = [nozzle_values]
    nozzles = [x for x in (_float(v) for v in nozzle_values) if x is not None]
    image_url = _orca_cover(model, path, tree)
    source_url = "https://github.com/OrcaSlicer/OrcaSlicer/blob/main/" + quote(path, safe="/")
    return {
        "provider": PROVIDER_INFO["orca"], "provider_id": "orca", "key": path,
        "manufacturer": vendor.replace("_", " "), "model": model, "name": model, "technology": "FDM",
        "build_x": bx, "build_y": by, "build_z": bz, "nozzle_mm": nozzles[0] if nozzles else None,
        "nozzle_options": nozzles, "resolution_x": None, "resolution_y": None,
        "xy_resolution_x_um": None, "xy_resolution_y_um": None, "screen_width_mm": None, "screen_height_mm": None,
        "image_url": image_url, "source_url": source_url, "source_license": "AGPL-3.0",
        "capabilities": {
            "printer_structure": raw.get("printer_structure"), "extruder_type": raw.get("extruder_type"),
            "gcode_flavor": raw.get("gcode_flavor"), "nozzle_type": raw.get("nozzle_type"),
            "default_print_profile": raw.get("default_print_profile"),
        },
        "source_snapshot": raw,
    }


def _search_orca(q: str, limit: int) -> list[dict[str, Any]]:
    tree = _orca_tree()
    paths = [p for p in tree if p.startswith("resources/profiles/") and "/machine/" in p and p.endswith(".json")]
    scored = []
    for p in paths:
        s = _score(q, Path(p).stem, p.split("/")[2] if len(p.split("/")) > 2 else "")
        if s and not re.search(r"^(?:fdm_)|common|base|fdm_machine", Path(p).stem, re.I): scored.append((s, p))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    grouped: dict[str, tuple[int, dict[str, Any]]] = {}
    # Fetch a modest number of the best candidate variant files. Data is cached locally.
    for score, p in scored[: min(50, max(limit * 3, 18))]:
        try:
            d = _orca_detail(p, tree)
        except Exception:
            continue
        key = _norm(d["manufacturer"] + " " + d["model"])
        # Prefer an ordinary 0.4 mm variant where available.
        bonus = 5 if abs(float(d.get("nozzle_mm") or 0) - 0.4) < 0.001 else 0
        if key not in grouped or score + bonus > grouped[key][0]: grouped[key] = (score + bonus, d)
    rows = [v[1] for v in sorted(grouped.values(), key=lambda x: -x[0])]
    return rows[:limit]


# ---------------- UVtools / Resin ----------------

def _uv_tree() -> list[str]:
    if _UV_PROFILE_ROOT and _UV_PROFILE_ROOT.is_dir():
        return ["PrusaSlicer/printer/" + path.name for path in _UV_PROFILE_ROOT.glob("*.ini") if path.is_file()]
    data = _fetch_json("uvtools-tree", "https://api.github.com/repos/sn4k3/UVtools/git/trees/master?recursive=1", 12 * 3600)
    return [x.get("path", "") for x in data.get("tree", []) if x.get("type") == "blob" and str(x.get("path", "")).startswith("PrusaSlicer/printer/") and str(x.get("path", "")).endswith(".ini")]


def _parse_ini_loose(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line: continue
        k, v = line.split("=", 1); out[k.strip()] = v.strip()
    return out


def _uv_file(path: str) -> tuple[dict[str, str], str]:
    if ".." in path or not path.startswith("PrusaSlicer/printer/") or not path.endswith(".ini"):
        raise KeyError("Invalid UVtools printer profile path")
    local = None
    if _UV_PROFILE_ROOT:
        candidate = (_UV_PROFILE_ROOT / Path(path).name).resolve()
        try:
            candidate.relative_to(_UV_PROFILE_ROOT.resolve())
            local = candidate if candidate.is_file() else None
        except ValueError:
            local = None
    if local:
        text = local.read_text(encoding="utf-8")
    else:
        raw_url = "https://raw.githubusercontent.com/sn4k3/UVtools/master/" + quote(path, safe="/")
        text = _fetch_text("uvtools-file-" + hashlib.sha1(path.encode()).hexdigest(), raw_url)
    return _parse_ini_loose(text), text


def _uv_detail(path: str) -> dict[str, Any]:
    vals, text = _uv_file(path)
    stem = Path(path).stem
    parts = stem.split(" ", 1)
    manufacturer = parts[0] if parts else ""
    model = parts[1] if len(parts) > 1 else stem
    bx = _float(vals.get("display_width")); by = _float(vals.get("display_height")); bz = _float(vals.get("max_print_height"))
    rx = _int(vals.get("display_pixels_x")); ry = _int(vals.get("display_pixels_y"))
    xum = round(bx / rx * 1000, 3) if bx and rx else None
    yum = round(by / ry * 1000, 3) if by and ry else None
    source_url = "https://github.com/sn4k3/UVtools/blob/master/" + quote(path, safe="/")
    result = {
        "provider": PROVIDER_INFO["uvtools"], "provider_id": "uvtools", "key": path,
        "manufacturer": manufacturer, "model": model, "name": stem, "technology": "MSLA / Resin",
        "build_x": bx, "build_y": by, "build_z": bz, "nozzle_mm": None, "nozzle_options": [],
        "resolution_x": rx, "resolution_y": ry, "xy_resolution_x_um": xum, "xy_resolution_y_um": yum,
        "screen_width_mm": bx, "screen_height_mm": by, "image_url": "", "source_url": source_url, "source_license": "AGPL-3.0",
        "capabilities": {
            "display_orientation": vals.get("display_orientation"), "sla_archive_format": vals.get("sla_archive_format"),
            "min_exposure_time": _float(vals.get("min_exposure_time")), "max_exposure_time": _float(vals.get("max_exposure_time")),
        },
        "source_snapshot": {"values": vals, "profile_text_sha256": hashlib.sha256(text.encode()).hexdigest()},
    }
    artwork = local_image_for_printer(manufacturer, model)
    if artwork:
        result["image_url"] = artwork.get("image_url") or ""
        result["artwork_provider_id"] = artwork.get("provider_id") or ""
        result["artwork_key"] = artwork.get("key") or ""
        result["artwork_source_url"] = artwork.get("source_url") or ""
    return result


def _search_uv(q: str, limit: int) -> list[dict[str, Any]]:
    scored = []
    for p in _uv_tree():
        stem = Path(p).stem
        if stem.casefold() in _UNVERIFIED_UV_PROFILE_STEMS:
            continue
        s = _score(q, stem)
        if s: scored.append((s, p))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    out = []
    for _, p in scored[:limit]:
        try: out.append(_uv_detail(p))
        except Exception: pass
    return out


def providers() -> list[dict[str, Any]]:
    return list(PROVIDER_INFO.values())


def _printer_identity(item: dict[str, Any]) -> str:
    """Return a provider-independent machine identity for catalogue merging."""
    maker, model = _printer_parts(str(item.get("manufacturer") or ""), str(item.get("model") or item.get("name") or ""))
    return f"{maker}:{model}" if model else ""


def _merge_catalogue_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge the same printer from multiple databases without losing artwork."""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in results:
        identity = _printer_identity(item) or f"{item.get('provider_id')}:{item.get('key')}"
        if identity not in merged:
            merged[identity] = dict(item)
            merged[identity]["source_providers"] = [item.get("provider_id")]
            order.append(identity)
            continue
        current = merged[identity]
        # Prefer the record carrying an image as the primary import source.
        if item.get("image_url") and not current.get("image_url"):
            replacement = dict(item)
            replacement["source_providers"] = list(current.get("source_providers") or [])
            for key, value in current.items():
                if replacement.get(key) in (None, "", [], {}):
                    replacement[key] = value
            current = merged[identity] = replacement
        else:
            for key, value in item.items():
                if current.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
                    current[key] = value
        providers = list(current.get("source_providers") or [])
        if item.get("provider_id") and item["provider_id"] not in providers:
            providers.append(item["provider_id"])
        current["source_providers"] = providers
        current["merged_source_count"] = len(providers)
    return [merged[key] for key in order]


def search(query: str, provider: str = "all", technology: str = "all", limit: int = 30) -> dict[str, Any]:
    q = (query or "").strip()
    if len(q) < 2: return {"results": [], "warnings": [], "query": q}
    wanted = set(PROVIDER_INFO) if provider in {"", "all"} else {provider}
    if technology.lower() == "fdm": wanted &= {"orca"}
    elif technology.lower() in {"resin", "msla", "sla", "dlp"}: wanted &= {"uvtools", "dragonfruit"}
    results: list[dict[str, Any]] = []; warnings: list[str] = []
    if "orca" in wanted:
        try: results.extend(_search_orca(q, limit))
        except Exception as exc: warnings.append(f"OrcaSlicer: {exc}")
    if "uvtools" in wanted:
        try: results.extend(_search_uv(q, limit))
        except Exception as exc: warnings.append(f"UVtools: {exc}")
    if "dragonfruit" in wanted:
        try: results.extend(_search_dragonfruit(q, limit))
        except Exception as exc: warnings.append(f"DragonFruit: {exc}")
    if provider in {"", "all"}:
        results = _merge_catalogue_results(results)
    results.sort(key=lambda r: (_score(q, r.get("manufacturer"), r.get("model")) * -1, r.get("manufacturer", ""), r.get("model", "")))
    return {"results": results[:limit], "warnings": warnings, "query": q}


def detail(provider: str, key: str) -> dict[str, Any]:
    if provider == "orca": return _orca_detail(key)
    if provider == "uvtools": return _uv_detail(key)
    if provider == "dragonfruit": return _dragonfruit_detail(key)
    raise KeyError("Unknown printer catalogue provider")


def image(provider: str, key: str) -> tuple[bytes, str]:
    if provider == "dragonfruit":
        record = _dragonfruit_index().get(key)
        if not record: raise KeyError("DragonFruit printer image not found")
        path: Path = record["asset"]
        return path.read_bytes(), (mimetypes.guess_type(path.name)[0] or "image/png")
    d = detail(provider, key)
    url = str(d.get("image_url") or "")
    if not url: raise KeyError("This source does not publish a printer image")
    if url.startswith("dragonfruit://"):
        return image("dragonfruit", url.removeprefix("dragonfruit://"))
    if url.startswith("printer-art://"):
        path = _bundled_printer_art(url)
        if not path: raise KeyError("Bundled printer artwork not found")
        return path.read_bytes(), (mimetypes.guess_type(path.name)[0] or "image/png")
    if provider == "orca" and url.startswith("orca-local://"):
        path = _orca_local_path(url.removeprefix("orca-local://"))
        if not path: raise KeyError("Bundled OrcaSlicer printer image not found")
        return path.read_bytes(), (mimetypes.guess_type(path.name)[0] or "image/png")
    if _is_direct_image_url(url):
        return _fetch_image(f"{provider}:{key}", url)
    if (urlparse(url).hostname or "").casefold() in _OFFICIAL_PRINTER_HOSTS:
        return _official_page_image(url)
    return _fetch_image(f"{provider}:{key}", url)


def remote_image(url: str, cache_key: str) -> tuple[bytes, str]:
    if url.startswith("printer-art://"):
        path = _bundled_printer_art(url)
        if not path: raise KeyError("Bundled printer artwork not found")
        return path.read_bytes(), (mimetypes.guess_type(path.name)[0] or "image/png")
    if _is_direct_image_url(url):
        return _fetch_image(cache_key, url)
    if (urlparse(url).hostname or "").casefold() in _OFFICIAL_PRINTER_HOSTS:
        return _official_page_image(url)
    return _fetch_image(cache_key, url)
