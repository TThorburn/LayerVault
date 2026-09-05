from __future__ import annotations

import math
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np

ENGINE_NAME = "LayerVault Mesh Health"
ENGINE_VERSION = "5"
SUPPORTED = {".stl", ".obj", ".3mf"}


@dataclass
class MeshData:
    vertices: np.ndarray
    faces: np.ndarray
    source_format: str
    notes: list[str]


def _empty(fmt: str, note: str = "") -> MeshData:
    return MeshData(np.empty((0, 3), dtype=np.float64), np.empty((0, 3), dtype=np.int64), fmt, [note] if note else [])


def _dedupe_triangle_vertices(raw: np.ndarray, decimals: int = 6) -> tuple[np.ndarray, np.ndarray]:
    if raw.size == 0:
        return np.empty((0, 3), dtype=np.float64), np.empty((0, 3), dtype=np.int64)
    rounded = np.round(raw.astype(np.float64, copy=False), decimals=decimals)
    vertices, inverse = np.unique(rounded, axis=0, return_inverse=True)
    faces = inverse.reshape((-1, 3)).astype(np.int64, copy=False)
    return vertices, faces


def _unique_faces_by_geometry(vertices: np.ndarray, faces: np.ndarray, decimals: int = 6) -> tuple[np.ndarray, int]:
    """Remove duplicate triangles by coordinates, independent of vertex indexes/winding."""
    if len(faces) == 0:
        return faces, 0
    # Map every rounded coordinate triplet to one stable ID, then sort the three
    # IDs in each face. Sorting X/Y/Z columns independently is not valid: two
    # different triangles can have the same per-axis value sets.
    rounded = np.round(np.asarray(vertices, dtype=np.float64), decimals=decimals)
    _, coordinate_ids = np.unique(rounded, axis=0, return_inverse=True)
    canonical = np.sort(coordinate_ids[faces], axis=1)
    _, first = np.unique(canonical, axis=0, return_index=True)
    first = np.sort(first)
    return faces[first], int(len(faces) - len(first))


def _repair_duplicate_faces(vertices: np.ndarray, faces: np.ndarray, decimals: int = 6) -> tuple[np.ndarray, dict[str, int]]:
    """Remove duplicate faces without turning isolated two-sided sheets into holes.

    A normal duplicate on a solid surface has neighbouring faces on its three
    edges, so one representative must remain. A reverse-wound coincident pair
    whose edges are used only by that pair is a zero-thickness sheet; both faces
    must be removed or the survivor becomes an open triangular boundary.
    """
    stats = {"duplicate_groups": 0, "duplicate_excess_faces": 0, "removed_faces": 0, "isolated_sheet_groups": 0, "isolated_sheet_faces": 0}
    if len(faces) == 0:
        return faces, stats
    rounded = np.round(np.asarray(vertices, dtype=np.float64), decimals=decimals)
    _, coordinate_ids = np.unique(rounded, axis=0, return_inverse=True)
    coordinate_faces = coordinate_ids[faces]
    canonical = np.sort(coordinate_faces, axis=1)
    _, inverse, counts = np.unique(canonical, axis=0, return_inverse=True, return_counts=True)
    duplicate_group_ids = np.flatnonzero(counts > 1)
    if not len(duplicate_group_ids):
        return faces, stats
    coordinate_topology = _edge_topology(coordinate_faces)
    remove = np.zeros(len(faces), dtype=bool)
    for group_id in duplicate_group_ids:
        indexes = np.flatnonzero(inverse == group_id)
        occurrence_count = len(indexes)
        first_index = int(indexes[0])
        edge_positions = np.arange(first_index * 3, first_index * 3 + 3)
        edge_counts = coordinate_topology["edge_counts"][coordinate_topology["inverse"][edge_positions]]
        isolated_sheet = bool(np.all(edge_counts == occurrence_count))
        stats["duplicate_groups"] += 1
        stats["duplicate_excess_faces"] += occurrence_count - 1
        if isolated_sheet:
            remove[indexes] = True
            stats["isolated_sheet_groups"] += 1
            stats["isolated_sheet_faces"] += occurrence_count
            stats["removed_faces"] += occurrence_count
        else:
            remove[indexes[1:]] = True
            stats["removed_faces"] += occurrence_count - 1
    return faces[~remove], stats


def load_stl(path: Path) -> MeshData:
    size = path.stat().st_size
    with path.open("rb") as fh:
        head = fh.read(84)
        if len(head) >= 84:
            count = struct.unpack("<I", head[80:84])[0]
            if 84 + count * 50 == size:
                raw = np.empty((count * 3, 3), dtype=np.float32)
                for i in range(count):
                    chunk = fh.read(50)
                    if len(chunk) != 50:
                        return _empty("STL", "Binary STL ended unexpectedly")
                    vals = struct.unpack("<12fH", chunk)
                    raw[i * 3 : i * 3 + 3] = ((vals[3], vals[4], vals[5]), (vals[6], vals[7], vals[8]), (vals[9], vals[10], vals[11]))
                vertices, faces = _dedupe_triangle_vertices(raw)
                return MeshData(vertices, faces, "STL", [])

    verts: list[tuple[float, float, float]] = []
    for line in path.read_text(errors="ignore").splitlines():
        parts = line.strip().split()
        if len(parts) >= 4 and parts[0].lower() == "vertex":
            try:
                verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
            except ValueError:
                continue
    raw = np.asarray(verts, dtype=np.float64)
    usable = len(raw) - (len(raw) % 3)
    raw = raw[:usable]
    vertices, faces = _dedupe_triangle_vertices(raw)
    return MeshData(vertices, faces, "STL", [] if usable else ["No STL triangles were found"])


def load_obj(path: Path) -> MeshData:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    notes: list[str] = []
    with path.open("r", errors="ignore") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if parts[0] == "v" and len(parts) >= 4:
                try:
                    vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
                except ValueError:
                    pass
            elif parts[0] == "f" and len(parts) >= 4:
                idx: list[int] = []
                for token in parts[1:]:
                    try:
                        raw = int(token.split("/")[0])
                        idx.append(raw - 1 if raw > 0 else len(vertices) + raw)
                    except Exception:
                        idx = []
                        break
                if len(idx) >= 3:
                    for i in range(1, len(idx) - 1):
                        faces.append((idx[0], idx[i], idx[i + 1]))
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64).reshape((-1, 3)) if faces else np.empty((0, 3), dtype=np.int64)
    if f.size and (f.min() < 0 or f.max() >= len(v)):
        notes.append("OBJ contains face indexes outside the vertex list")
        good = np.all((f >= 0) & (f < len(v)), axis=1)
        f = f[good]
    return MeshData(v, f, "OBJ", notes)


def load_3mf(path: Path) -> MeshData:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    notes = ["3MF health analysis inspects embedded triangle meshes; component/build transforms are not yet expanded."]
    try:
        with zipfile.ZipFile(path) as zf:
            for name in [n for n in zf.namelist() if n.lower().endswith(".model")]:
                root = ET.fromstring(zf.read(name))
                for mesh in [el for el in root.iter() if el.tag.split("}")[-1] == "mesh"]:
                    local_vertices: list[tuple[float, float, float]] = []
                    local_faces: list[tuple[int, int, int]] = []
                    for el in mesh.iter():
                        tag = el.tag.split("}")[-1]
                        if tag == "vertex":
                            try:
                                local_vertices.append((float(el.attrib["x"]), float(el.attrib["y"]), float(el.attrib["z"])))
                            except Exception:
                                pass
                        elif tag == "triangle":
                            try:
                                local_faces.append((int(el.attrib["v1"]), int(el.attrib["v2"]), int(el.attrib["v3"])))
                            except Exception:
                                pass
                    base = len(vertices)
                    vertices.extend(local_vertices)
                    faces.extend((a + base, b + base, c + base) for a, b, c in local_faces)
    except Exception as exc:
        return _empty("3MF", f"3MF could not be parsed: {exc}")
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64).reshape((-1, 3)) if faces else np.empty((0, 3), dtype=np.int64)
    return MeshData(v, f, "3MF", notes)


def load_mesh(path: Path) -> MeshData:
    ext = path.suffix.lower()
    if ext == ".stl":
        return load_stl(path)
    if ext == ".obj":
        return load_obj(path)
    if ext == ".3mf":
        return load_3mf(path)
    return _empty(ext.lstrip(".").upper() or "Unknown", "This file type does not contain directly analysable triangle geometry")


def _edge_topology(faces: np.ndarray) -> dict[str, Any]:
    if len(faces) == 0:
        return {"unique_edges": 0, "boundary_edges": 0, "nonmanifold_edges": 0, "broken_faces": 0, "winding_consistent": False, "edge_counts": np.empty(0, dtype=np.int64), "inverse": np.empty(0, dtype=np.int64), "edges_directed": np.empty((0,2),dtype=np.int64), "edges_unique": np.empty((0,2),dtype=np.int64)}
    edges_directed = faces[:, [[0, 1], [1, 2], [2, 0]]].reshape((-1, 2))
    edges_sorted = np.sort(edges_directed, axis=1)
    edges_unique, inverse, counts = np.unique(edges_sorted, axis=0, return_inverse=True, return_counts=True)
    boundary = counts == 1
    nonmanifold = counts > 2
    bad = counts != 2
    broken_faces = int(np.count_nonzero(bad[inverse].reshape((-1, 3)).any(axis=1)))
    direction = np.where(edges_directed[:, 0] < edges_directed[:, 1], 1, -1)
    direction_sum = np.bincount(inverse, weights=direction, minlength=len(counts))
    manifold_pairs = counts == 2
    winding_consistent = bool(np.all(np.abs(direction_sum[manifold_pairs]) < 0.5)) if np.any(manifold_pairs) else False
    return {
        "unique_edges": int(len(edges_unique)),
        "boundary_edges": int(np.count_nonzero(boundary)),
        "nonmanifold_edges": int(np.count_nonzero(nonmanifold)),
        "broken_faces": broken_faces,
        "winding_consistent": winding_consistent,
        "edge_counts": counts,
        "inverse": inverse,
        "edges_directed": edges_directed,
        "edges_unique": edges_unique,
    }


def _component_count(vertex_count: int, faces: np.ndarray) -> int:
    if vertex_count == 0 or len(faces) == 0:
        return 0
    parent = np.arange(vertex_count, dtype=np.int64)
    rank = np.zeros(vertex_count, dtype=np.int8)

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = int(parent[x])
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            parent[ra] = rb
        elif rank[ra] > rank[rb]:
            parent[rb] = ra
        else:
            parent[rb] = ra
            rank[ra] += 1

    for a, b, c in faces:
        union(int(a), int(b)); union(int(b), int(c))
    used = np.unique(faces)
    roots = {find(int(x)) for x in used}
    return len(roots)


def _face_geometry(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    if len(faces) == 0:
        return np.empty((0,3)), np.empty(0), 0.0, 0.0
    tri = vertices[faces]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    double_area = np.linalg.norm(cross, axis=1)
    area = double_area * 0.5
    signed_volume = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)
    return cross, area, float(area.sum()), signed_volume


def analyse_mesh(mesh: MeshData) -> dict[str, Any]:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(vertices) == 0 or len(faces) == 0:
        return {
            "analyzable": False,
            "engine": ENGINE_NAME,
            "engine_version": ENGINE_VERSION,
            "source_format": mesh.source_format,
            "grade": "Unavailable",
            "score": 0,
            "summary": "No triangle mesh could be analysed.",
            "metrics": {},
            "issues": [{"code":"no_mesh","severity":"info","title":"Triangle mesh unavailable","detail": mesh.notes[0] if mesh.notes else "This asset is stored normally but cannot be topology-checked yet.","repairable":False}],
            "recommendations": [],
            "notes": mesh.notes,
        }

    valid_index = np.all((faces >= 0) & (faces < len(vertices)), axis=1)
    invalid_faces = int(len(faces) - np.count_nonzero(valid_index))
    faces = faces[valid_index]
    topo = _edge_topology(faces)
    cross, area_each, area_total, signed_volume = _face_geometry(vertices, faces)
    bounds_min = vertices.min(axis=0); bounds_max = vertices.max(axis=0); extents = bounds_max - bounds_min
    scale = max(float(np.max(extents)), 1.0)
    eps_area = max(1e-14, (scale * scale) * 1e-12)
    degenerate = int(np.count_nonzero(area_each <= eps_area))
    _, duplicate_classification = _repair_duplicate_faces(vertices, faces)
    duplicate_faces = duplicate_classification["duplicate_excess_faces"]
    components = _component_count(len(vertices), faces)
    watertight = bool(topo["boundary_edges"] == 0 and topo["nonmanifold_edges"] == 0 and invalid_faces == 0)
    positive_volume = bool(signed_volume > 0)
    euler = int(len(vertices) - topo["unique_edges"] + len(faces))

    metrics = {
        "vertices": int(len(vertices)),
        "faces": int(len(faces)),
        "unique_edges": topo["unique_edges"],
        "boundary_edges": topo["boundary_edges"],
        "nonmanifold_edges": topo["nonmanifold_edges"],
        "broken_faces": topo["broken_faces"],
        "degenerate_faces": degenerate,
        "duplicate_faces": duplicate_faces,
        "isolated_duplicate_sheet_groups": duplicate_classification["isolated_sheet_groups"],
        "isolated_duplicate_sheet_faces": duplicate_classification["isolated_sheet_faces"],
        "invalid_faces": invalid_faces,
        "components": int(components),
        "watertight": watertight,
        "winding_consistent": bool(topo["winding_consistent"]),
        "normals_outward_likely": positive_volume if watertight else None,
        "surface_area_mm2": round(area_total, 3),
        "signed_volume_mm3": round(signed_volume, 3),
        "volume_mm3": round(abs(signed_volume), 3) if watertight else None,
        "euler_number": euler,
        "bounds_min_mm": [round(float(x), 4) for x in bounds_min],
        "bounds_max_mm": [round(float(x), 4) for x in bounds_max],
        "dimensions_mm": [round(float(x), 4) for x in extents],
    }

    issues: list[dict[str, Any]] = []
    def issue(code: str, severity: str, title: str, detail: str, repairable: bool = False):
        issues.append({"code":code,"severity":severity,"title":title,"detail":detail,"repairable":repairable})

    if invalid_faces:
        issue("invalid_faces", "error", "Invalid face references", f"{invalid_faces:,} faces reference missing vertices.", True)
    if topo["nonmanifold_edges"]:
        issue("nonmanifold_edges", "error", "Non-manifold edges", f"{topo['nonmanifold_edges']:,} edges are shared by more than two faces. Slicers may interpret the solid unpredictably.", False)
    if topo["boundary_edges"]:
        issue("open_edges", "warning", "Open boundaries", f"{topo['boundary_edges']:,} boundary edges leave the surface open, affecting {topo['broken_faces']:,} faces.", True)
    if not topo["winding_consistent"]:
        issue("winding", "warning", "Inconsistent face winding", "Some neighbouring faces point around shared edges in the same direction. This can produce flipped normals.", True)
    if watertight and not positive_volume:
        issue("inverted", "warning", "Likely inverted shell", "The closed mesh has a negative signed volume, meaning its triangle normals are probably facing inward. Many slicers auto-correct this, but it can confuse hollowing, booleans and inside/outside calculations. Safe Repair can reverse the shell without changing its shape.", True)
    if degenerate:
        issue("degenerate", "warning", "Degenerate triangles", f"{degenerate:,} triangles have effectively zero area.", True)
    if duplicate_faces:
        if duplicate_classification["isolated_sheet_groups"]:
            issue("duplicate", "warning", "Zero-thickness duplicate sheets", f"{duplicate_classification['isolated_sheet_groups']:,} edge-isolated duplicate groups contain {duplicate_classification['isolated_sheet_faces']:,} coincident faces. Safe Repair can remove each complete two-sided sheet without opening the surrounding model.", True)
        else:
            issue("duplicate", "warning", "Duplicate triangles", f"{duplicate_faces:,} duplicate faces were detected.", True)
    if components > 1:
        issue("multiple_shells", "info", "Multiple disconnected shells", f"The file contains {components:,} disconnected mesh bodies. This may be intentional for multi-part models.", False)
    if len(faces) > 1_000_000:
        issue("very_dense", "info", "Very dense mesh", f"{len(faces):,} faces may make editing and slicing slower even if the model is healthy.", False)

    score = 100
    score -= min(45, topo["nonmanifold_edges"] * 2)
    score -= 25 if topo["boundary_edges"] else 0
    score -= 15 if not topo["winding_consistent"] else 0
    score -= min(15, degenerate + duplicate_faces)
    score -= 20 if invalid_faces else 0
    score -= 8 if watertight and not positive_volume else 0
    score = max(0, int(score))
    if any(i["severity"] == "error" for i in issues) or score < 55:
        grade = "Issues"
        summary = "Geometry problems are likely to affect reliable slicing."
    elif any(i["severity"] == "warning" for i in issues) or score < 90:
        grade = "Review"
        summary = "The mesh is usable in many slicers, but there are geometry warnings worth reviewing."
    else:
        grade = "Healthy"
        summary = "The mesh is closed and topologically clean by LayerVault's current checks."

    recommendations = []
    if any(i["repairable"] for i in issues):
        recommendations.append("Create a Safe Repair version to clean duplicates/degenerates and normalise face orientation without overwriting this file.")
    if topo["boundary_edges"]:
        recommendations.append("Small simple boundary loops can be closed automatically; larger or complex holes should be inspected visually after repair.")
    if components > 1:
        recommendations.append("Confirm that multiple disconnected shells are intentional before printing or applying future boolean/hollow operations.")
    if not issues:
        recommendations.append("No topology repair is indicated. You can move on to orientation, sizing and printer-specific preparation.")

    return {
        "analyzable": True,
        "engine": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "source_format": mesh.source_format,
        "grade": grade,
        "score": score,
        "summary": summary,
        "metrics": metrics,
        "issues": issues,
        "recommendations": recommendations,
        "notes": mesh.notes,
    }


def analyse_file(path: Path) -> dict[str, Any]:
    return analyse_mesh(load_mesh(path))


def printer_fit(report: dict[str, Any], printer: dict[str, Any] | None) -> dict[str, Any] | None:
    if not printer or not report.get("analyzable"):
        return None
    dims = report.get("metrics", {}).get("dimensions_mm") or []
    build = [printer.get("build_x"), printer.get("build_y"), printer.get("build_z")]
    if len(dims) != 3 or any(x is None for x in build):
        return {"available": False, "reason": "Printer build dimensions are incomplete."}
    d = [float(x) for x in dims]; b = [float(x) for x in build]
    current = all(d[i] <= b[i] + 1e-9 for i in range(3))
    permutations = [
        (0,1,2),(0,2,1),(1,0,2),(1,2,0),(2,0,1),(2,1,0)
    ]
    fits = []
    for perm in permutations:
        oriented = [d[perm[0]], d[perm[1]], d[perm[2]]]
        if all(oriented[i] <= b[i] + 1e-9 for i in range(3)):
            margins = [b[i] - oriented[i] for i in range(3)]
            fits.append((min(margins), perm, oriented, margins))
    best = max(fits, key=lambda x: x[0]) if fits else None
    return {
        "available": True,
        "fits_current_orientation": current,
        "fits_with_axis_rotation": bool(best),
        "model_dimensions_mm": [round(x,3) for x in d],
        "build_volume_mm": [round(x,3) for x in b],
        "best_axis_order": list(best[1]) if best else None,
        "best_oriented_dimensions_mm": [round(x,3) for x in best[2]] if best else None,
        "margins_mm": [round(x,3) for x in best[3]] if best else None,
        "technology": printer.get("technology"),
        "resolution_x": printer.get("resolution_x"),
        "resolution_y": printer.get("resolution_y"),
        "xy_resolution_x_um": printer.get("xy_resolution_x_um"),
        "xy_resolution_y_um": printer.get("xy_resolution_y_um"),
        "nozzle_mm": printer.get("nozzle_mm"),
    }


def _reindex(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(faces) == 0:
        return vertices[:0], faces
    used = np.unique(faces)
    mapping = np.full(len(vertices), -1, dtype=np.int64)
    mapping[used] = np.arange(len(used), dtype=np.int64)
    return vertices[used], mapping[faces]


def _orient_faces_consistently(faces: np.ndarray) -> tuple[np.ndarray, int]:
    """Orient manifold face patches consistently. Returns faces and number flipped."""
    if len(faces) == 0:
        return faces, 0
    edges = faces[:, [[0,1],[1,2],[2,0]]].reshape((-1,2))
    edge_faces = np.repeat(np.arange(len(faces), dtype=np.int64), 3)
    sorted_edges = np.sort(edges, axis=1)
    _, inv, counts = np.unique(sorted_edges, axis=0, return_inverse=True, return_counts=True)
    order = np.argsort(inv, kind="stable")
    starts = np.cumsum(np.r_[0, counts[:-1]])
    adjacency: list[list[tuple[int,bool]]] = [[] for _ in range(len(faces))]
    dirs = edges[:,0] < edges[:,1]
    for group, count in enumerate(counts):
        if count != 2:
            continue
        positions = order[starts[group]:starts[group]+2]
        e1,e2 = int(positions[0]),int(positions[1]); f1,f2=int(edge_faces[e1]),int(edge_faces[e2])
        same = bool(dirs[e1] == dirs[e2])
        adjacency[f1].append((f2,same)); adjacency[f2].append((f1,same))
    parity = np.full(len(faces), -1, dtype=np.int8)
    for start in range(len(faces)):
        if parity[start] != -1: continue
        parity[start] = 0; stack=[start]
        while stack:
            cur=stack.pop()
            for nxt, toggle in adjacency[cur]:
                desired = int(parity[cur] ^ int(toggle))
                if parity[nxt] == -1:
                    parity[nxt]=desired; stack.append(nxt)
    out=faces.copy(); mask=parity==1
    if np.any(mask): out[mask]=out[mask][:,[0,2,1]]
    return out, int(np.count_nonzero(mask))


def _simple_boundary_loops(faces: np.ndarray) -> list[list[int]]:
    topo=_edge_topology(faces)
    counts=topo["edge_counts"]; inv=topo["inverse"]; directed=topo["edges_directed"]
    boundary_positions=np.flatnonzero(counts[inv]==1)
    if not len(boundary_positions): return []
    # Walk the boundary as an undirected degree-2 graph. This works even when
    # the damaged faces do not yet have consistent winding.
    boundary=np.sort(directed[boundary_positions],axis=1)
    adjacency: dict[int,list[int]]={}
    for a,b in boundary:
        ai,bi=int(a),int(b)
        adjacency.setdefault(ai,[]).append(bi); adjacency.setdefault(bi,[]).append(ai)
    loops=[]; used:set[tuple[int,int]]=set()
    for a,b in boundary:
        start,cur,nxt=int(a),int(a),int(b)
        first_edge=(min(cur,nxt),max(cur,nxt))
        if first_edge in used: continue
        loop=[start]
        for _ in range(len(boundary)+1):
            used.add((min(cur,nxt),max(cur,nxt))); loop.append(nxt)
            if nxt==start: break
            candidates=[x for x in adjacency.get(nxt,[]) if (min(nxt,x),max(nxt,x)) not in used]
            if len(adjacency.get(nxt,[]))!=2 or len(candidates)!=1: break
            cur,nxt=nxt,candidates[0]
        if len(loop)>=4 and loop[-1]==start:
            loops.append(loop[:-1])
    return loops


def safe_repair(mesh: MeshData) -> tuple[MeshData, dict[str, Any]]:
    v=mesh.vertices.copy(); f=mesh.faces.copy(); actions=[]
    if len(f)==0: return mesh, {"actions":[],"changed":False}
    valid=np.all((f>=0)&(f<len(v)),axis=1); removed_invalid=int(len(f)-np.count_nonzero(valid))
    if removed_invalid: f=f[valid]; actions.append(f"Removed {removed_invalid:,} invalid face(s)")
    _, areas, _, _=_face_geometry(v,f); scale=max(float(np.ptp(v,axis=0).max()),1.0); eps=max(1e-14,scale*scale*1e-12)
    good=areas>eps; removed_degen=int(len(f)-np.count_nonzero(good))
    if removed_degen: f=f[good]; actions.append(f"Removed {removed_degen:,} degenerate triangle(s)")
    f,duplicate_cleanup=_repair_duplicate_faces(v,f)
    removed_dup=duplicate_cleanup["removed_faces"]
    if duplicate_cleanup["isolated_sheet_faces"]:
        actions.append(f"Removed {duplicate_cleanup['isolated_sheet_faces']:,} faces forming {duplicate_cleanup['isolated_sheet_groups']:,} isolated two-sided duplicate sheet(s)")
    ordinary_removed=removed_dup-duplicate_cleanup["isolated_sheet_faces"]
    if ordinary_removed: actions.append(f"Removed {ordinary_removed:,} duplicate triangle(s) while preserving the surface")
    f,flipped=_orient_faces_consistently(f)
    if flipped: actions.append(f"Re-oriented {flipped:,} face(s) for consistent winding")
    # Close only tiny, unambiguous triangle/quad boundary loops.
    loops=_simple_boundary_loops(f); additions=[]
    for loop in loops:
        if len(loop)==3: additions.append((loop[0],loop[2],loop[1]))
        elif len(loop)==4:
            additions.extend([(loop[0],loop[2],loop[1]),(loop[0],loop[3],loop[2])])
    if additions:
        f=np.vstack([f,np.asarray(additions,dtype=np.int64)]); actions.append(f"Closed {len(additions):,} triangle(s) across small boundary holes")
        f,_=_orient_faces_consistently(f)
    # Boundary repair must never reintroduce a duplicate that cleanup removed.
    f,final_duplicate_cleanup=_repair_duplicate_faces(v,f)
    removed_final_dup=final_duplicate_cleanup["removed_faces"]
    if removed_final_dup: actions.append(f"Removed {removed_final_dup:,} duplicate triangle(s) introduced during boundary cleanup")
    v,f=_reindex(v,f)
    # If the result is closed but globally inverted, flip every face.
    report=analyse_mesh(MeshData(v,f,mesh.source_format,mesh.notes))
    if report.get("metrics",{}).get("watertight") and report.get("metrics",{}).get("signed_volume_mm3",0)<0:
        f=f[:,[0,2,1]]; actions.append("Flipped the closed shell outward")
    changed=bool(actions)
    return MeshData(v,f,"STL",list(mesh.notes)), {"actions":actions,"changed":changed}


def write_binary_stl(path: Path, mesh: MeshData) -> None:
    vertices=np.asarray(mesh.vertices,dtype=np.float64); faces=np.asarray(mesh.faces,dtype=np.int64)
    if len(faces)>0xFFFFFFFF: raise ValueError("STL face count exceeds binary format limit")
    tri=vertices[faces]
    normals=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]); lengths=np.linalg.norm(normals,axis=1); nz=lengths>0; normals[nz]/=lengths[nz,None]
    records=np.zeros(len(faces),dtype=np.dtype([('normal','<f4',(3,)),('vertices','<f4',(9,)),('attribute','<u2')]))
    records['normal']=normals.astype(np.float32,copy=False); records['vertices']=tri.reshape((-1,9)).astype(np.float32,copy=False)
    with path.open("wb") as fh:
        header=b"LayerVault safe repair"[:80].ljust(80,b"\0"); fh.write(header); fh.write(struct.pack("<I",len(faces))); records.tofile(fh)


def repair_file(source: Path, target: Path) -> dict[str, Any]:
    before_mesh=load_mesh(source); before=analyse_mesh(before_mesh)
    repaired,meta=safe_repair(before_mesh); write_binary_stl(target,repaired)
    # Verify the bytes that will actually be imported, not only the in-memory mesh.
    after=analyse_mesh(load_mesh(target))
    bm,am=before.get("metrics",{}),after.get("metrics",{})
    regressions=[]
    if int(after.get("score") or 0) < int(before.get("score") or 0): regressions.append("health score decreased")
    if int(am.get("boundary_edges") or 0) > int(bm.get("boundary_edges") or 0): regressions.append("open boundary count increased")
    if int(am.get("nonmanifold_edges") or 0) > int(bm.get("nonmanifold_edges") or 0): regressions.append("non-manifold edge count increased")
    if int(am.get("duplicate_faces") or 0) > int(bm.get("duplicate_faces") or 0): regressions.append("duplicate face count increased")
    if regressions:
        target.unlink(missing_ok=True)
        return {"before":before,"after":before,"actions":[],"changed":False,"validation_error":"Safe Repair rejected the candidate because " + ", ".join(regressions) + ". The original was left unchanged."}
    return {"before":before,"after":after,"actions":meta["actions"],"changed":meta["changed"],"validation_error":None}

# ---------------------------------------------------------------------------
# Pass 10.1: printer-aware manufacturing / printability screening
# ---------------------------------------------------------------------------

MANUFACTURING_ENGINE_NAME = "LayerVault Printability"
MANUFACTURING_ENGINE_VERSION = "3"


def _face_sample(vertices: np.ndarray, faces: np.ndarray, max_faces: int = 18000):
    if len(faces) == 0:
        return (np.empty((0, 3)), np.empty((0, 3)), np.empty(0), np.empty((0, 3), dtype=np.int64))
    step = max(1, int(math.ceil(len(faces) / max_faces)))
    sf = faces[::step]
    tri = vertices[sf]
    cent = tri.mean(axis=1)
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(cross, axis=1)
    normals = np.divide(cross, length[:, None], out=np.zeros_like(cross), where=length[:, None] > 1e-15)
    area = length * 0.5
    return cent, normals, area, sf


def _opposing_surface_samples(vertices: np.ndarray, faces: np.ndarray, max_search_mm: float, max_faces: int = 14000) -> dict[str, Any]:
    """Return bounded opposing-surface samples, including both sides of every match.

    The numpy arrays in this private result are intentionally not JSON serialisable. Keeping the
    paired face indexes lets the resin-preparation pass distinguish a substantial thin feature from an
    isolated close fold and thicken both sides without changing mesh connectivity.
    """
    cent, normals, areas, sf = _face_sample(vertices, faces, max_faces=max_faces)
    if len(cent) < 2 or max_search_mm <= 0:
        return {"available": False, "reason": "Not enough triangle geometry for thickness screening.", "centroids": cent, "normals": normals, "areas": areas, "sample_faces": sf, "pairs": []}
    # Work with outward-facing normals even when a whole watertight mesh was authored inverted.
    # This is a bounded proxy over the same deterministic face sample used below.
    sampled_triangles = vertices[sf]
    signed_volume_proxy = float(np.einsum("ij,ij->i", sampled_triangles[:, 0], np.cross(sampled_triangles[:, 1], sampled_triangles[:, 2])).sum())
    if signed_volume_proxy < 0:
        normals = -normals
    cell = max(float(max_search_mm), 0.05)
    keys = np.floor(cent / cell).astype(np.int64)
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for i, key in enumerate(keys):
        buckets.setdefault(tuple(int(x) for x in key), []).append(i)
    values: list[tuple[float, int, int]] = []
    offsets = [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)]
    for i, keyv in enumerate(keys):
        n = normals[i]
        if not np.any(n):
            continue
        candidates: list[int] = []
        base = tuple(int(x) for x in keyv)
        for dx, dy, dz in offsets:
            candidates.extend(buckets.get((base[0] + dx, base[1] + dy, base[2] + dz), ()))
        if len(candidates) > 1200:
            stride = max(1, len(candidates) // 1200)
            candidates = candidates[::stride]
        if not candidates:
            continue
        ci = cent[i]
        best = None
        best_j = -1
        for j in candidates:
            if j == i:
                continue
            # Opposing surfaces should have substantially opposing normals.
            if float(np.dot(n, normals[j])) > -0.35:
                continue
            dv = cent[j] - ci
            dist = float(np.linalg.norm(dv))
            if dist <= 1e-5 or dist > max_search_mm:
                continue
            # A real wall lies behind the outward normal of the first surface and in front of
            # the outward normal of the partner. Merely taking the absolute projection used to
            # mistake costume folds and adjacent details facing across empty air for material.
            inward_a = -float(np.dot(dv, n))
            inward_b = float(np.dot(dv, normals[j]))
            if inward_a <= 1e-5 or inward_b <= 1e-5:
                continue
            projected = (inward_a + inward_b) * 0.5
            if projected > max_search_mm:
                continue
            lateral = math.sqrt(max(0.0, dist * dist - projected * projected))
            # Reject nearby folds/adjacent facets that are mostly lateral rather than opposite.
            if lateral > max(projected * 0.9, 0.12):
                continue
            if best is None or projected < best:
                best = projected
                best_j = int(j)
        if best is not None:
            values.append((best, i, best_j))
    if not values:
        return {"available": False, "reason": "No reliable opposing-surface samples were found.", "centroids": cent, "normals": normals, "areas": areas, "sample_faces": sf, "pairs": []}
    values.sort(key=lambda x: x[0])
    return {"available": True, "centroids": cent, "normals": normals, "areas": areas, "sample_faces": sf, "pairs": values}


def _broad_thin_regions(samples: dict[str, Any], face_count: int, target_mm: float) -> list[dict[str, Any]]:
    """Group opposing samples into substantial thin, approximately sheet-like candidates.

    A raw minimum alone is not enough: detailed miniatures contain many close curls and sharp
    creases. A repair candidate must occupy a useful physical span, form a locally flat point
    cloud and be substantial relative to the other candidates on the same model.
    """
    if not samples.get("available") or target_mm <= 0:
        return []
    cent = samples["centroids"]
    normals = samples["normals"]
    areas = samples["areas"]
    unique: dict[tuple[int, int], tuple[float, int, int]] = {}
    for thickness, i, j in samples.get("pairs", []):
        key = tuple(sorted((int(i), int(j))))
        current = unique.get(key)
        if current is None or thickness < current[0]:
            unique[key] = (float(thickness), int(i), int(j))
    pairs = [x for x in unique.values() if 0.005 <= x[0] < target_mm]
    if not pairs:
        return []
    midpoints = np.asarray([(cent[i] + cent[j]) * 0.5 for _, i, j in pairs], dtype=np.float64)
    cell = max(0.45, min(0.8, target_mm * 1.3))
    keys = np.floor(midpoints / cell).astype(np.int64)
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for index, key in enumerate(keys):
        buckets.setdefault(tuple(int(x) for x in key), []).append(index)
    active = set(buckets)
    seen: set[tuple[int, int, int]] = set()
    step_weight = max(1.0, float(face_count) / max(1, len(samples["sample_faces"])))
    regions: list[dict[str, Any]] = []
    for start in active:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        cells = []
        while stack:
            key = stack.pop()
            cells.append(key)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        nxt = (key[0] + dx, key[1] + dy, key[2] + dz)
                        if nxt in active and nxt not in seen:
                            seen.add(nxt)
                            stack.append(nxt)
        indexes = [index for key in cells for index in buckets[key]]
        points = midpoints[indexes]
        values = np.asarray([pairs[index][0] for index in indexes], dtype=np.float64)
        span = np.ptp(points, axis=0) if len(points) else np.zeros(3)
        largest_span = float(span.max())
        sample_area = float(sum(areas[pairs[index][1]] for index in indexes))
        estimated_area = sample_area * step_weight
        if len(points) >= 4 and np.any(span > 1e-8):
            eig, eigvec = np.linalg.eigh(np.cov(points.T))
            flatness = float(eig[0] / max(eig[-1], 1e-9))
            sheet_normal = eigvec[:, 0]
        else:
            # Low-poly thin panels can have only two sampled triangles, but their face area is large.
            flatness = 0.0
            sheet_normal = normals[pairs[indexes[0]][1]].copy()
        low_poly = face_count <= 500
        physically_broad = largest_span >= max(1.2, target_mm * 2.4) or (low_poly and estimated_area >= max(2.0, target_mm * 8.0))
        sufficiently_sampled = len(indexes) >= 6 or (low_poly and estimated_area >= max(2.0, target_mm * 6.0))
        if not physically_broad or not sufficiently_sampled or flatness > 0.14:
            continue
        centre = points.mean(axis=0)
        representative = min(indexes, key=lambda index: float(np.linalg.norm(midpoints[index] - centre)))
        # One substantial feature group can contain several lobes or branches. Spread the marker
        # locations over its extent so Show on model points at the geometry, not only its root.
        desired_markers = min(7, max(1, int(math.ceil(estimated_area / max(7.5, target_mm * 15.0)))))
        marker_indexes = [representative]
        while len(marker_indexes) < min(desired_markers, len(indexes)):
            remaining = [index for index in indexes if index not in marker_indexes]
            if not remaining:
                break
            next_index = max(
                remaining,
                key=lambda index: min(float(np.linalg.norm(midpoints[index] - midpoints[chosen])) for chosen in marker_indexes),
            )
            if min(float(np.linalg.norm(midpoints[next_index] - midpoints[chosen])) for chosen in marker_indexes) < max(0.9, target_mm * 2.0):
                break
            marker_indexes.append(next_index)
        regional_p25 = float(np.percentile(values, 25)) if len(values) >= 4 else float(np.median(values))
        regional_p10 = float(np.percentile(values, 10)) if len(values) >= 8 else float(np.min(values))
        regions.append({
            "pair_indexes": indexes,
            "pairs": pairs,
            "position_mm": [round(float(x), 3) for x in midpoints[representative]],
            "estimated_p25_mm": round(regional_p25, 3),
            "estimated_p10_mm": round(regional_p10, 3),
            "estimated_median_mm": round(float(np.median(values)), 3),
            "estimated_sheet_area_mm2": round(estimated_area, 2),
            "span_mm": [round(float(x), 2) for x in span],
            "sample_count": int(len(indexes)),
            "flatness": round(flatness, 4),
            "normal_coherence": round(float(np.linalg.eigvalsh(normals[[pairs[index][1] for index in indexes]].T @ normals[[pairs[index][1] for index in indexes]])[-1] / max(1, len(indexes))), 3),
            "_sheet_normal": sheet_normal,
            "_marker_positions": [[round(float(x), 3) for x in midpoints[index]] for index in marker_indexes],
        })
    if regions:
        # Prioritise the substantial exposed feature groups and suppress small connected outfit,
        # ornament and surface-detail patches when a much larger thin feature is present. Small
        # models still retain a candidate once its sampled area reaches 3.5 mm².
        dominant_area = max(float(item["estimated_sheet_area_mm2"]) for item in regions)
        selected_area_floor = max(3.5, dominant_area * 0.24)
        regions = [item for item in regions if float(item["estimated_sheet_area_mm2"]) >= selected_area_floor]
    regions.sort(key=lambda item: (item["estimated_p25_mm"], -item["estimated_sheet_area_mm2"]))
    return regions


def _public_thin_regions(regions: list[dict[str, Any]], target_mm: float) -> list[dict[str, Any]]:
    return [
        {k: value for k, value in region.items() if k not in ("pair_indexes", "pairs") and not k.startswith("_")}
        | {"target_thickness_mm": round(float(target_mm), 3), "marker_positions": region.get("_marker_positions") or [region["position_mm"]]}
        for region in regions
    ]


def _opposing_surface_thickness(vertices: np.ndarray, faces: np.ndarray, max_search_mm: float, max_faces: int = 14000) -> dict[str, Any]:
    """Estimate local wall thickness using nearby sampled, oppositely-facing triangle centroids.

    This is deliberately a screening heuristic, not an exact medial-axis thickness solver. It
    works well for thin walls and exposed features while staying bounded on dense meshes.
    """
    samples = _opposing_surface_samples(vertices, faces, max_search_mm, max_faces=max_faces)
    if not samples.get("available"):
        return {"available": False, "reason": samples.get("reason", "Thickness screening was inconclusive.")}
    cent = samples["centroids"]
    values = samples["pairs"]
    arr = np.asarray([v[0] for v in values], dtype=np.float64)
    # Avoid presenting one pathological numerical sample as a definitive minimum.
    p05 = float(np.percentile(arr, 5)) if len(arr) >= 20 else float(arr[0])
    p10 = float(np.percentile(arr, 10)) if len(arr) >= 10 else float(arr[0])
    markers = []
    taken: list[np.ndarray] = []
    separation = max(max_search_mm * 0.6, 0.35)
    # Mark representative low-quantile samples, not the absolute numerical outliers. On detailed
    # miniatures the latter are usually tiny folds/curls and used to obscure substantial features.
    marker_low = max(float(arr[0]), float(np.percentile(arr, 2)) if len(arr) >= 50 else float(arr[0]))
    marker_high = max(p10, marker_low + 0.03)
    marker_values = [v for v in values if marker_low <= v[0] <= marker_high]
    if not marker_values:
        marker_values = values[: max(80, min(len(values), 300))]
    for thickness, idx, _ in marker_values:
        pt = cent[idx]
        if any(float(np.linalg.norm(pt - old)) < separation for old in taken):
            continue
        taken.append(pt)
        markers.append({"position_mm": [round(float(x), 3) for x in pt], "estimated_thickness_mm": round(float(thickness), 3)})
        if len(markers) >= 18:
            break
    regions = _broad_thin_regions(samples, len(faces), min(0.5, max_search_mm))
    public_regions = _public_thin_regions(regions, min(0.5, max_search_mm))
    broad_markers = []
    for region in public_regions[:16]:
        for position in region.get("marker_positions") or [region["position_mm"]]:
            broad_markers.append({
                "position_mm": position,
                "estimated_thickness_mm": region["estimated_p10_mm"],
                "target_thickness_mm": region["target_thickness_mm"],
                "estimated_sheet_area_mm2": region["estimated_sheet_area_mm2"],
            })
            if len(broad_markers) >= 18:
                break
        if len(broad_markers) >= 18:
            break
    return {
        "available": True,
        "sample_count": int(len(arr)),
        "estimated_min_mm": round(float(arr[0]), 3),
        "estimated_p05_mm": round(p05, 3),
        "estimated_p10_mm": round(p10, 3),
        "median_mm": round(float(np.median(arr)), 3),
        "markers": markers,
        "broad_thin_regions": public_regions,
        "broad_region_markers": broad_markers,
        "method": "inward-facing sampled opposing surfaces",
    }


def _component_labels(vertex_count: int, faces: np.ndarray) -> tuple[np.ndarray, int]:
    if vertex_count == 0 or len(faces) == 0:
        return np.full(vertex_count, -1, dtype=np.int64), 0
    parent = np.arange(vertex_count, dtype=np.int64)
    rank = np.zeros(vertex_count, dtype=np.int8)
    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = int(parent[x])
        return x
    def union(a: int, b: int):
        ra, rb = find(a), find(b)
        if ra == rb: return
        if rank[ra] < rank[rb]: parent[ra] = rb
        elif rank[ra] > rank[rb]: parent[rb] = ra
        else: parent[rb] = ra; rank[ra] += 1
    for a, b, c in faces:
        union(int(a), int(b)); union(int(b), int(c))
    used = np.unique(faces)
    roots = np.asarray([find(int(v)) for v in used], dtype=np.int64)
    uniq, inv = np.unique(roots, return_inverse=True)
    labels = np.full(vertex_count, -1, dtype=np.int64)
    labels[used] = inv
    return labels, int(len(uniq))


def _nested_cavity_screen(vertices: np.ndarray, faces: np.ndarray) -> dict[str, Any]:
    labels, count = _component_labels(len(vertices), faces)
    if count <= 1:
        return {"candidate_count": 0, "candidates": [], "note": "No separate nested closed shell was detected."}
    comps = []
    for label in range(count):
        mask = np.all(labels[faces] == label, axis=1)
        cf = faces[mask]
        if len(cf) == 0: continue
        used = np.unique(cf); vv = vertices[used]
        mn, mx = vv.min(axis=0), vv.max(axis=0)
        _, _, _, sv = _face_geometry(vertices, cf)
        topo = _edge_topology(cf)
        comps.append({"label": label, "min": mn, "max": mx, "signed_volume": sv,
                      "watertight": topo["boundary_edges"] == 0 and topo["nonmanifold_edges"] == 0,
                      "faces": int(len(cf))})
    candidates = []
    for inner in comps:
        if not inner["watertight"]: continue
        for outer in comps:
            if inner is outer or not outer["watertight"]: continue
            margin = np.minimum(inner["min"] - outer["min"], outer["max"] - inner["max"])
            if np.all(margin > 1e-4):
                candidates.append({
                    "inner_shell": int(inner["label"]), "outer_shell": int(outer["label"]),
                    "inner_faces": inner["faces"],
                    "opposite_orientation": bool(inner["signed_volume"] * outer["signed_volume"] < 0),
                    "minimum_enclosure_margin_mm": round(float(np.min(margin)), 3),
                })
                break
    return {"candidate_count": len(candidates), "candidates": candidates[:8],
            "note": "Nested closed shells can represent intentionally hollow geometry, but without a vent/drain path they can trap uncured resin."}


def _local_minima_screen(vertices: np.ndarray, faces: np.ndarray, tolerance_mm: float = 0.08) -> dict[str, Any]:
    if len(vertices) == 0 or len(faces) == 0:
        return {"candidate_count": 0, "markers": []}
    z = vertices[:, 2]
    minz = float(z.min()); span = max(float(z.max() - minz), 1e-6)
    nbr_min = np.full(len(vertices), np.inf, dtype=np.float64)
    edges = faces[:, [[0,1],[1,2],[2,0]]].reshape((-1,2))
    np.minimum.at(nbr_min, edges[:,0], z[edges[:,1]])
    np.minimum.at(nbr_min, edges[:,1], z[edges[:,0]])
    clearance = max(tolerance_mm, span * 0.0005)
    mask = (z + clearance < nbr_min) & (z > minz + max(0.15, span * 0.002)) & np.isfinite(nbr_min)
    idx = np.flatnonzero(mask)
    if not len(idx):
        return {"candidate_count": 0, "markers": []}
    pts = vertices[idx]
    cell = max(0.4, min(2.0, max(float(np.ptp(vertices[:,0])), float(np.ptp(vertices[:,1]))) / 80.0))
    groups: dict[tuple[int,int], list[int]] = {}
    for raw_idx, p in zip(idx, pts):
        groups.setdefault((int(math.floor(p[0]/cell)), int(math.floor(p[1]/cell))), []).append(int(raw_idx))
    markers = []
    for members in groups.values():
        p = vertices[members].mean(axis=0)
        markers.append({"position_mm": [round(float(x),3) for x in p], "z_above_base_mm": round(float(p[2]-minz),3)})
    markers.sort(key=lambda x: x["z_above_base_mm"])
    return {"candidate_count": len(markers), "raw_local_minima": int(len(idx)), "markers": markers[:24]}


def _peel_cross_section_proxy(vertices: np.ndarray, faces: np.ndarray, bins: int = 48) -> dict[str, Any]:
    if len(faces) == 0:
        return {"available": False}
    tri = vertices[faces]
    cross = np.cross(tri[:,1]-tri[:,0], tri[:,2]-tri[:,0])
    projected_xy = np.abs(cross[:,2]) * 0.5
    zc = tri[:,:,2].mean(axis=1)
    zmin, zmax = float(vertices[:,2].min()), float(vertices[:,2].max())
    span = zmax - zmin
    if span <= 1e-9:
        return {"available": False}
    bi = np.clip(((zc-zmin)/span*bins).astype(int),0,bins-1)
    sums = np.bincount(bi,weights=projected_xy,minlength=bins)
    peak = float(sums.max()) if len(sums) else 0.0
    nz = sums[sums > 1e-9]
    median = float(np.median(nz)) if len(nz) else 0.0
    jumps = np.diff(sums)
    jump = float(jumps.max()) if len(jumps) else 0.0
    peak_bin = int(np.argmax(sums)) if len(sums) else 0
    return {"available": True, "bins": bins, "peak_projected_area_mm2": round(peak,2),
            "median_projected_area_mm2": round(median,2), "largest_upward_jump_mm2": round(max(0.0,jump),2),
            "peak_z_mm": round(zmin + (peak_bin+0.5)*span/bins,2)}


def _downward_pocket_screen(vertices: np.ndarray, faces: np.ndarray) -> dict[str, Any]:
    """Low-confidence resin suction screening in the current +Z build direction.

    Downward-facing surface patches are grouped in XY. A patch is only reported when nearby
    mostly-vertical faces point *toward* the patch centre, which is a useful distinction between
    a concave cup wall and the convex outside of an ordinary box/underside.
    """
    if len(faces) == 0: return {"candidate_count":0,"candidates":[]}
    tri = vertices[faces]
    cent = tri.mean(axis=1)
    cross = np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]); mag=np.linalg.norm(cross,axis=1)
    normals=np.divide(cross,mag[:,None],out=np.zeros_like(cross),where=mag[:,None]>1e-15)
    area=mag*.5
    mn=vertices.min(axis=0); mx=vertices.max(axis=0); extent=mx-mn
    if extent[0] <= 1e-6 or extent[1] <= 1e-6: return {"candidate_count":0,"candidates":[]}
    nx=ny=40
    ix=np.clip(((cent[:,0]-mn[0])/extent[0]*nx).astype(int),0,nx-1)
    iy=np.clip(((cent[:,1]-mn[1])/extent[1]*ny).astype(int),0,ny-1)
    down=np.zeros((nx,ny),dtype=np.float64); zsum=np.zeros((nx,ny)); zcount=np.zeros((nx,ny),dtype=np.int32)
    side_nx=np.zeros((nx,ny));side_ny=np.zeros((nx,ny));side_w=np.zeros((nx,ny))
    downward=(normals[:,2] < -0.35) & (cent[:,2] > mn[2] + max(.25,extent[2]*.005))
    dw=np.flatnonzero(downward)
    if len(dw):
        weight=area[dw]*np.abs(normals[dw,2])
        np.add.at(down,(ix[dw],iy[dw]),weight*.4)
        np.add.at(zsum,(ix[dw],iy[dw]),cent[dw,2]); np.add.at(zcount,(ix[dw],iy[dw]),1)
        # Add triangle vertices as coverage samples so broad low-poly pocket ceilings do not disappear between grid cells.
        for corner in range(3):
            pts=tri[dw,corner]; vx=np.clip(((pts[:,0]-mn[0])/extent[0]*nx).astype(int),0,nx-1);vy=np.clip(((pts[:,1]-mn[1])/extent[1]*ny).astype(int),0,ny-1)
            np.add.at(down,(vx,vy),weight*.2)
            np.add.at(zsum,(vx,vy),pts[:,2]);np.add.at(zcount,(vx,vy),1)
    side=np.abs(normals[:,2]) < .70
    sw=np.flatnonzero(side)
    if len(sw):
        np.add.at(side_nx,(ix[sw],iy[sw]),normals[sw,0]*area[sw]*.4);np.add.at(side_ny,(ix[sw],iy[sw]),normals[sw,1]*area[sw]*.4);np.add.at(side_w,(ix[sw],iy[sw]),area[sw]*.4)
        for corner in range(3):
            pts=tri[sw,corner];vx=np.clip(((pts[:,0]-mn[0])/extent[0]*nx).astype(int),0,nx-1);vy=np.clip(((pts[:,1]-mn[1])/extent[1]*ny).astype(int),0,ny-1)
            np.add.at(side_nx,(vx,vy),normals[sw,0]*area[sw]*.2);np.add.at(side_ny,(vx,vy),normals[sw,1]*area[sw]*.2);np.add.at(side_w,(vx,vy),area[sw]*.2)
    cell_area=(extent[0]/nx)*(extent[1]/ny)
    seed=down >= max(.02,cell_area*.10)
    active=seed.copy()
    # One-cell dilation connects a broad surface represented by sparse triangle samples.
    active[1:,:] |= seed[:-1,:]; active[:-1,:] |= seed[1:,:]; active[:,1:] |= seed[:,:-1]; active[:,:-1] |= seed[:,1:]
    seen=set(); groups=[]
    for x,y in zip(*np.nonzero(active)):
        if (int(x),int(y)) in seen: continue
        stack=[(int(x),int(y))]; seen.add((int(x),int(y))); cells=[]
        while stack:
            cx,cy=stack.pop();cells.append((cx,cy))
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                n=(cx+dx,cy+dy)
                if 0<=n[0]<nx and 0<=n[1]<ny and active[n] and n not in seen: seen.add(n);stack.append(n)
        area_sum=sum(float(down[a,b]) for a,b in cells)
        if area_sum < max(2.0,cell_area*1.5): continue
        centre=np.array([np.mean([mn[0]+(a+.5)*extent[0]/nx for a,b in cells]),np.mean([mn[1]+(b+.5)*extent[1]/ny for a,b in cells])])
        cellset=set(cells);ring=set();boundary_cells=set()
        for a,b in cells:
            is_boundary=False
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                n=(a+dx,b+dy)
                if not (0<=n[0]<nx and 0<=n[1]<ny):
                    is_boundary=True
                elif n not in cellset:
                    ring.add(n);is_boundary=True
            if is_boundary:boundary_cells.add((a,b))
        inward=[]
        for a,b in (ring | boundary_cells):
            if side_w[a,b] <= 1e-8: continue
            nxy=np.array([side_nx[a,b]/side_w[a,b],side_ny[a,b]/side_w[a,b]])
            nl=float(np.linalg.norm(nxy))
            if nl<=1e-8:continue
            pos=np.array([mn[0]+(a+.5)*extent[0]/nx,mn[1]+(b+.5)*extent[1]/ny]);toward=centre-pos;tl=float(np.linalg.norm(toward))
            if tl<=1e-8:continue
            inward.append(float(np.dot(nxy/nl,toward/tl)))
        # Positive values mean side normals face into the downward patch: concave pocket.
        if len(inward)<2 or float(np.mean(inward)) < .15: continue
        wz=[]
        for a,b in cells:
            if zcount[a,b]:wz.append(zsum[a,b]/zcount[a,b])
        groups.append({"projected_area_proxy_mm2":round(area_sum,2),"position_mm":[round(float(centre[0]),2),round(float(centre[1]),2),round(float(np.mean(wz)) if wz else float(mn[2]),2)],"cells":len(cells),"concavity_score":round(float(np.mean(inward)),2)})
    groups.sort(key=lambda x:x["projected_area_proxy_mm2"],reverse=True)
    return {"candidate_count":len(groups),"candidates":groups[:12],"confidence":"low",
            "note":"Candidates combine downward-facing surface with surrounding faces oriented into the pocket. Slice preview remains the final authority for suction-cup confirmation."}


def _fdm_overhang_screen(vertices: np.ndarray, faces: np.ndarray, nozzle_mm: float) -> dict[str, Any]:
    if len(faces)==0:return {"available":False}
    tri=vertices[faces];cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);mag=np.linalg.norm(cross,axis=1);area=mag*.5
    normals=np.divide(cross,mag[:,None],out=np.zeros_like(cross),where=mag[:,None]>1e-15)
    cent=tri.mean(axis=1);minz=float(vertices[:,2].min());span=max(float(vertices[:,2].max()-minz),1e-6)
    above=cent[:,2] > minz + max(.25,span*.003)
    over=above & (normals[:,2] < -0.35); severe=above & (normals[:,2] < -0.70)
    total=float(area.sum()) or 1.0
    severe_area=float(area[severe].sum()); over_area=float(area[over].sum())
    edge_len=np.maximum.reduce([np.linalg.norm(tri[:,1]-tri[:,0],axis=1),np.linalg.norm(tri[:,2]-tri[:,1],axis=1),np.linalg.norm(tri[:,0]-tri[:,2],axis=1)])
    bridge=severe & (edge_len > max(1.5,float(nozzle_mm)*4))
    bottom=(np.abs(cent[:,2]-minz) < max(.12,float(nozzle_mm)*.35)) & (normals[:,2] < -0.65)
    contact=float(np.abs(cross[bottom,2]).sum()*.5)
    footprint=max(float(np.ptp(vertices[:,0])*np.ptp(vertices[:,1])),1e-6)
    return {"available":True,"overhang_area_mm2":round(over_area,2),"overhang_percent":round(over_area/total*100,2),
            "severe_overhang_area_mm2":round(severe_area,2),"severe_overhang_percent":round(severe_area/total*100,2),
            "bridge_candidate_faces":int(np.count_nonzero(bridge)),"bed_contact_proxy_mm2":round(contact,2),
            "bed_contact_vs_footprint_percent":round(contact/footprint*100,2)}


def _area_weighted_vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    normals = np.zeros_like(vertices, dtype=np.float64)
    if not len(faces):
        return normals
    tri = vertices[faces]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    for corner in range(3):
        np.add.at(normals, faces[:, corner], cross)
    length = np.linalg.norm(normals, axis=1)
    return np.divide(normals, length[:, None], out=np.zeros_like(normals), where=length[:, None] > 1e-15)


def _thicken_broad_thin_regions(mesh: MeshData, target_mm: float, _passes_remaining: int = 1) -> tuple[MeshData, dict[str, Any]]:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    samples = _opposing_surface_samples(vertices, faces, max(1.2, target_mm * 2.4), max_faces=14000)
    regions = [region for region in _broad_thin_regions(samples, len(faces), target_mm) if float(region.get("estimated_p25_mm") or target_mm) < target_mm * 0.92]
    if not regions:
        return mesh, {"changed": False, "region_count": 0, "moved_vertices": 0, "target_thickness_mm": round(target_mm, 3), "markers": []}
    # Bound the operation on ornate models. The most delicate/largest substantial candidates are
    # first; isolated curls and small adjacent details fail the exposed-region screen.
    regions = sorted(regions, key=lambda item: (item["estimated_p25_mm"], -item["estimated_sheet_area_mm2"]))[:24]
    vertex_normals = _area_weighted_vertex_normals(vertices, faces)
    seeds: list[tuple[np.ndarray, np.ndarray, float, np.ndarray]] = []
    seen_pairs: set[tuple[int, int]] = set()
    for region in regions:
        pairs = region["pairs"]
        for pair_index in region["pair_indexes"]:
            thickness, i, j = pairs[pair_index]
            key = tuple(sorted((int(i), int(j))))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            displacement = max(0.0, (target_mm - float(thickness)) * 0.515)
            if displacement <= 0.001:
                continue
            for side in (int(i), int(j)):
                # Expand each sampled side along its own local outward direction. Unlike the old
                # one-direction PCA offset, this follows differently oriented sections without
                # blending directions across the two sides of a thin feature.
                direction = np.asarray(samples["normals"][side], dtype=np.float64)
                direction /= max(float(np.linalg.norm(direction)), 1e-15)
                seeds.append((samples["centroids"][side], direction, displacement, samples["sample_faces"][side]))
    if not seeds:
        return mesh, {"changed": False, "region_count": len(regions), "moved_vertices": 0, "target_thickness_mm": round(target_mm, 3), "markers": _public_thin_regions(regions, target_mm)}
    radius = max(0.65, min(1.1, target_mm * 1.8))
    vertex_keys = np.floor(vertices / radius).astype(np.int64)
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for index, key in enumerate(vertex_keys):
        buckets.setdefault(tuple(int(x) for x in key), []).append(index)
    displacement = np.zeros(len(vertices), dtype=np.float64)
    displacement_vector = np.zeros_like(vertices, dtype=np.float64)
    offsets = [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)]
    for position, direction, amount, seed_vertices in seeds:
        seed_vertices = np.asarray(seed_vertices, dtype=np.int64)
        stronger_seed = amount > displacement[seed_vertices]
        if np.any(stronger_seed):
            selected_seed = seed_vertices[stronger_seed]
            displacement[selected_seed] = amount
            displacement_vector[selected_seed] = direction * amount
        base = tuple(int(x) for x in np.floor(position / radius))
        candidates: list[int] = []
        for dx, dy, dz in offsets:
            candidates.extend(buckets.get((base[0] + dx, base[1] + dy, base[2] + dz), ()))
        if not candidates:
            continue
        indexes = np.asarray(candidates, dtype=np.int64)
        delta = vertices[indexes] - position
        distance = np.linalg.norm(delta, axis=1)
        alignment = vertex_normals[indexes] @ direction
        valid = (distance <= radius) & (alignment >= 0.42)
        if not np.any(valid):
            continue
        indexes = indexes[valid]
        distance = distance[valid]
        # A broad plateau joins sparse sampled faces; the outer 45% is a smooth blend into the
        # unmodified attachment instead of a hard ridge.
        weight = np.clip((radius - distance) / (radius * 0.45), 0.0, 1.0)
        proposed = amount * weight
        stronger = proposed > displacement[indexes]
        if np.any(stronger):
            selected = indexes[stronger]
            displacement[selected] = proposed[stronger]
            displacement_vector[selected] = direction * proposed[stronger, None]
    moved = displacement > 1e-5
    if not np.any(moved):
        return mesh, {"changed": False, "region_count": len(regions), "moved_vertices": 0, "target_thickness_mm": round(target_mm, 3), "markers": _public_thin_regions(regions, target_mm)}
    adjusted = vertices.copy()
    adjusted[moved] += displacement_vector[moved]
    result_mesh = MeshData(adjusted, faces.copy(), mesh.source_format, list(mesh.notes))
    meta = {
        "changed": True,
        "region_count": len(regions),
        "moved_vertices": int(np.count_nonzero(moved)),
        "target_thickness_mm": round(target_mm, 3),
        "maximum_offset_mm": round(float(displacement.max()), 3),
        "markers": _public_thin_regions(regions, target_mm),
        "passes": 1,
    }
    if _passes_remaining > 1:
        refined, follow = _thicken_broad_thin_regions(result_mesh, target_mm, _passes_remaining - 1)
        if follow.get("changed"):
            meta["moved_vertices"] += int(follow.get("moved_vertices") or 0)
            meta["maximum_offset_mm"] = round(max(float(meta["maximum_offset_mm"]), float(follow.get("maximum_offset_mm") or 0)), 3)
            meta["passes"] += int(follow.get("passes") or 1)
            meta["remaining_region_count_after_first_pass"] = int(follow.get("region_count") or 0)
            result_mesh = refined
    return result_mesh, meta


def _resin_orientation_risk(vertices: np.ndarray, faces: np.ndarray) -> dict[str, Any]:
    pockets = _downward_pocket_screen(vertices, faces)
    minima = _local_minima_screen(vertices, faces)
    peel = _peel_cross_section_proxy(vertices, faces)
    return {
        "suction_candidates": int(pockets.get("candidate_count") or 0),
        "island_candidates": int(minima.get("candidate_count") or 0),
        "peak_peel_mm2": float(peel.get("peak_projected_area_mm2") or 0),
    }


def _reduce_suction_by_orientation(mesh: MeshData) -> tuple[MeshData, dict[str, Any]]:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    before = _resin_orientation_risk(vertices, faces)
    if before["suction_candidates"] <= 0:
        return mesh, {"changed": False, "before": before, "after": before, "orientation": "Stored orientation"}
    options = [
        ("X +90°", np.asarray(((1, 0, 0), (0, 0, -1), (0, 1, 0)), dtype=np.float64)),
        ("X -90°", np.asarray(((1, 0, 0), (0, 0, 1), (0, -1, 0)), dtype=np.float64)),
        ("Y +90°", np.asarray(((0, 0, 1), (0, 1, 0), (-1, 0, 0)), dtype=np.float64)),
        ("Y -90°", np.asarray(((0, 0, -1), (0, 1, 0), (1, 0, 0)), dtype=np.float64)),
        ("X 180°", np.asarray(((1, 0, 0), (0, -1, 0), (0, 0, -1)), dtype=np.float64)),
    ]
    centre = (vertices.min(axis=0) + vertices.max(axis=0)) * 0.5
    candidates = []
    for name, rotation in options:
        rotated = (vertices - centre) @ rotation.T + centre
        risk = _resin_orientation_risk(rotated, faces)
        # Never exchange one cup for a large island/peel regression. This is intentionally more
        # conservative than a slicer's interactive orientation optimiser.
        island_ok = risk["island_candidates"] <= before["island_candidates"] + 4
        peel_ok = risk["peak_peel_mm2"] <= max(before["peak_peel_mm2"] * 1.3, before["peak_peel_mm2"] + 40.0)
        if risk["suction_candidates"] < before["suction_candidates"] and island_ok and peel_ok:
            candidates.append((risk["suction_candidates"], risk["island_candidates"], risk["peak_peel_mm2"], name, rotated, risk))
    if not candidates:
        return mesh, {"changed": False, "before": before, "after": before, "orientation": "Stored orientation", "note": "No orthogonal orientation reduced suction candidates without a material island or peel-risk regression."}
    candidates.sort(key=lambda item: item[:3])
    _, _, _, name, rotated, after = candidates[0]
    return MeshData(rotated, faces.copy(), mesh.source_format, list(mesh.notes)), {"changed": True, "before": before, "after": after, "orientation": name}


def resin_prepare(mesh: MeshData, printer: dict[str, Any], target_thickness_mm: float = 0.5) -> tuple[MeshData, dict[str, Any]]:
    """Create a conservative, non-destructive resin-preparation candidate.

    Topology cleanup runs first. Substantial exposed thin features are offset to the requested target while mesh
    connectivity is retained. If suction candidates exist, six orthogonal build directions are
    screened and a rotation is accepted only when it reduces cups without a material island/peel
    regression. Automatic drain-hole placement is deliberately outside this safe operation.
    """
    technology = str(printer.get("technology") or "").lower()
    if not any(x in technology for x in ("resin", "sla", "msla", "dlp", "lcd")):
        raise ValueError("Resin Preparation requires a resin/SLA/MSLA/DLP printer profile.")
    target = min(2.0, max(0.3, float(target_thickness_mm)))
    topology_mesh, topology_meta = safe_repair(mesh)
    thickened, thickness_meta = _thicken_broad_thin_regions(topology_mesh, target, _passes_remaining=1)
    oriented, orientation_meta = _reduce_suction_by_orientation(thickened)
    actions = list(topology_meta.get("actions") or [])
    if thickness_meta.get("changed"):
        region_count = int(thickness_meta["region_count"])
        pass_count = int(thickness_meta.get("passes", 1))
        actions.append(f"Strengthened {region_count} exposed thin feature {'group' if region_count == 1 else 'groups'} toward {target:.2f} mm ({thickness_meta['moved_vertices']:,} vertex adjustments across {pass_count} {'pass' if pass_count == 1 else 'passes'})")
    if orientation_meta.get("changed"):
        actions.append(f"Rotated {orientation_meta['orientation']} to reduce suction candidates from {orientation_meta['before']['suction_candidates']} to {orientation_meta['after']['suction_candidates']}")
    return oriented, {
        "changed": bool(topology_meta.get("changed") or thickness_meta.get("changed") or orientation_meta.get("changed")),
        "actions": actions,
        "target_thickness_mm": round(target, 3),
        "topology": topology_meta,
        "thickness": thickness_meta,
        "orientation": orientation_meta,
    }


def manufacturing_analysis(mesh: MeshData, geometry_report: dict[str, Any], printer: dict[str, Any]) -> dict[str, Any]:
    if not geometry_report.get("analyzable"):
        return {"available":False,"summary":"Triangle geometry is unavailable for printability screening."}
    vertices=np.asarray(mesh.vertices,dtype=np.float64);faces=np.asarray(mesh.faces,dtype=np.int64)
    valid=np.all((faces>=0)&(faces<len(vertices)),axis=1) if len(faces) else np.empty(0,dtype=bool);faces=faces[valid]
    if len(faces)==0:return {"available":False,"summary":"No valid triangle faces are available."}
    technology=str(printer.get("technology") or "").lower()
    resin = any(x in technology for x in ("resin","sla","msla","dlp","lcd"))
    family="Resin" if resin else "FDM"
    nozzle=float(printer.get("nozzle_mm") or .4)
    pitch_um=max(float(printer.get("xy_resolution_x_um") or 0),float(printer.get("xy_resolution_y_um") or 0))
    if resin:
        critical=max(.18,(pitch_um/1000.0)*4 if pitch_um else .18)
        caution=max(.35,(pitch_um/1000.0)*8 if pitch_um else .35)
        max_search=max(1.2,caution*3.0)
    else:
        critical=max(.28,nozzle*.80);caution=max(.55,nozzle*1.50);max_search=max(1.8,caution*2.6)
    thickness=_opposing_surface_thickness(vertices,faces,max_search)
    if thickness.get("available"):
        vals=[]
        for m in thickness.get("markers",[]): vals.append(float(m["estimated_thickness_mm"]))
        thickness["critical_threshold_mm"]=round(critical,3);thickness["caution_threshold_mm"]=round(caution,3)
        thickness["critical_marker_count"]=sum(v<critical for v in vals);thickness["thin_marker_count"]=sum(v<caution for v in vals)
    minima=_local_minima_screen(vertices,faces)
    issues=[];recommendations=[];score=100
    def add(code,severity,title,detail,points=None):
        issues.append({"code":code,"severity":severity,"title":title,"detail":detail,"markers":points or []})
    if thickness.get("available"):
        p05=float(thickness.get("estimated_p05_mm") or 999)
        broad_regions=[x for x in thickness.get("broad_thin_regions",[]) if float(x.get("estimated_p25_mm") or 999) < caution]
        if resin and broad_regions:
            regional=min(float(x.get("estimated_p10_mm") or x.get("estimated_p25_mm") or 999) for x in broad_regions)
            severity="error" if regional < critical else "warning"
            score-=min(28,18+len(broad_regions)) if severity=="error" else min(22,10+len(broad_regions))
            markers=[]
            for region in broad_regions[:16]:
                for position in region.get("marker_positions") or [region["position_mm"]]:
                    markers.append({"position_mm":position,"estimated_thickness_mm":region.get("estimated_p10_mm") or region["estimated_p25_mm"],"target_thickness_mm":.5,"estimated_sheet_area_mm2":region.get("estimated_sheet_area_mm2")})
                    if len(markers)>=18:break
                if len(markers)>=18:break
            region_count=len(broad_regions)
            add("thin_exposed_feature",severity,"Exposed thin feature",f"LayerVault found {region_count} substantial thin feature {'group' if region_count == 1 else 'groups'} below the ~{caution:.2f} mm resin caution level; the lower regional estimate is about {regional:.2f} mm. Nearby surfaces facing across empty gaps are excluded, reducing false positives from folds and connected surface detail.",markers)
            recommendations.append("Use Show on model to inspect the exposed thin feature locations. Resin Preparation can strengthen the selected geometry toward 0.50 mm while keeping the original file unchanged.")
        elif p05 < critical:
            score-=18 if resin else 24;add("critical_thickness","error","Very thin geometry detected",f"Sampled opposing surfaces suggest regions around {p05:.2f} mm thick. For this {family.lower()} printer, LayerVault flags below ~{critical:.2f} mm as very delicate.",thickness.get("markers",[])[:12]);recommendations.append("Inspect the highlighted thin regions before printing; delicate features may need thickening or a different orientation.")
        elif p05 < caution:
            score-=6;add("thin_geometry","warning","Isolated thin samples",f"A few inward-facing material samples fall around {p05:.2f} mm, but they do not form a substantial exposed feature group. They are deliberately not highlighted or auto-thickened because small connected surface details can produce noisy local samples.")
    else:
        add("thickness_unavailable","info","Thickness estimate inconclusive",thickness.get("reason","LayerVault could not find enough opposing surface samples for a useful wall estimate."))
    result={"available":True,"engine":MANUFACTURING_ENGINE_NAME,"engine_version":MANUFACTURING_ENGINE_VERSION,"technology":family,
            "confidence":"Heuristic screening","score":0,"grade":"","summary":"","thickness":thickness,"issues":issues,"recommendations":recommendations,
            "build_direction":"+Z","analysis_note":"Printability checks are conservative geometry heuristics in the model's stored/current Z orientation; the slicer's layer preview remains the final authority."}
    if resin:
        cavities=_nested_cavity_screen(vertices,faces);pockets=_downward_pocket_screen(vertices,faces);peel=_peel_cross_section_proxy(vertices,faces)
        preparation_limit = float(thickness.get("caution_threshold_mm") or .35)
        broad_regions=[x for x in thickness.get("broad_thin_regions",[]) if float(x.get("estimated_p25_mm") or 999) < preparation_limit] if thickness.get("available") else []
        result["resin"]={"enclosed_cavities":cavities,"suction_pockets":pockets,"unsupported_minima":minima,"peel_proxy":peel,
                         "preparation":{"available":bool(broad_regions or pockets["candidate_count"]),"target_thickness_mm":.5,"thin_region_count":len(broad_regions),"suction_candidate_count":int(pockets["candidate_count"]),"can_thicken_broad_regions":bool(broad_regions),"can_try_safer_orientation":bool(pockets["candidate_count"]),"original_is_preserved":True,"drain_holes_automatic":False}}
        if cavities["candidate_count"]:
            score-=22;add("trapped_resin","error","Possible enclosed resin cavity",f"LayerVault found {cavities['candidate_count']} nested closed shell candidate(s). If these represent hollow space without a drain/vent path, uncured resin can remain trapped.");recommendations.append("Inspect hollow regions and ensure there are adequate drain and vent openings before printing.")
        if pockets["candidate_count"]:
            largest=pockets.get("candidates",[{}])[0]
            score-=min(18,6+pockets["candidate_count"]*2);add("suction_pocket","warning","Possible suction-pocket geometry",f"{pockets['candidate_count']} downward-facing concave pocket region(s) were found in the current +Z direction. The largest is around {float(largest.get('projected_area_proxy_mm2') or 0):.1f} mm² at Z {float((largest.get('position_mm') or [0,0,0])[2]):.1f} mm (concavity {float(largest.get('concavity_score') or 0):.2f}). Resin Preparation can test orthogonal orientations; it will not guess drain-hole placement.",[x for x in pockets['candidates'][:8]]);recommendations.append("Show the suspected pockets on the model, then confirm them in layer preview. Try the prepared orientation or add deliberate drain/vent holes in a dedicated hollowing tool if the pocket seals against the release film.")
        if minima["candidate_count"]:
            score-=min(14,4+minima["candidate_count"]//3);add("island_risk","warning","Unsupported-island risk",f"{minima['candidate_count']} local low-point region(s) begin above the model's lowest layer. These often need supports on resin printers.",minima.get("markers",[])[:12]);recommendations.append("Check the first appearance of these low points in layer preview and support any isolated islands.")
        if peel.get("available"):
            build_x=float(printer.get("build_x") or 0);build_y=float(printer.get("build_y") or 0);plate=build_x*build_y
            ratio=(float(peel.get("peak_projected_area_mm2") or 0)/plate*100) if plate>0 else 0
            peel["peak_vs_build_area_percent"]=round(ratio,2)
            if ratio>30 or float(peel.get("largest_upward_jump_mm2") or 0)>max(200,plate*.08):
                score-=8;add("peel_load","warning","Large cross-section / peel-load change",f"The orientation has a relatively large projected cross-section around Z {peel.get('peak_z_mm')} mm. Large abrupt sections can increase release-film peel forces.")
    else:
        fdm=_fdm_overhang_screen(vertices,faces,nozzle);result["fdm"]={"overhangs":fdm,"unsupported_minima":minima}
        if fdm.get("available") and fdm.get("severe_overhang_percent",0)>5:
            score-=min(18,int(fdm["severe_overhang_percent"]*.6));add("overhangs","warning","Unsupported overhang area",f"About {fdm['severe_overhang_percent']:.1f}% of sampled surface is steep downward-facing geometry above the first layer. Supports or reorientation may be needed.")
        if fdm.get("bridge_candidate_faces",0)>0:
            score-=min(8,2+fdm["bridge_candidate_faces"]//50);add("bridge_risk","info","Bridge-like regions detected",f"{fdm['bridge_candidate_faces']} near-horizontal downward face(s) span more than roughly four nozzle widths. Review bridging/support settings.")
        if fdm.get("bed_contact_vs_footprint_percent",100)<1.5:
            score-=10;add("bed_contact","warning","Small bed-contact footprint",f"Estimated downward-facing contact is only about {fdm['bed_contact_vs_footprint_percent']:.1f}% of the XY footprint. Adhesion may be sensitive to orientation or brim/support strategy.")
    score=max(0,int(score));result["score"]=score
    if any(x["severity"]=="error" for x in issues) or score<55: grade="Issues";summary=f"{family} printability has significant geometry risks to review."
    elif any(x["severity"]=="warning" for x in issues) or score<88: grade="Review";summary=f"The mesh is valid, but {family.lower()}-specific printability warnings are worth reviewing."
    else: grade="Ready";summary=f"No major {family.lower()}-specific manufacturing risk was found by the current screening checks."
    result["grade"]=grade;result["summary"]=summary
    if not recommendations:
        result["recommendations"].append("No strong printer-specific warning was detected. Confirm orientation/supports in the slicer's layer preview before printing.")
    return result


def manufacturing_analysis_file(path: Path, geometry_report: dict[str, Any], printer: dict[str, Any]) -> dict[str, Any]:
    return manufacturing_analysis(load_mesh(path), geometry_report, printer)


def resin_prepare_file(source: Path, target: Path, printer: dict[str, Any], target_thickness_mm: float = 0.5) -> dict[str, Any]:
    before_mesh = load_mesh(source)
    before = analyse_mesh(before_mesh)
    prepared, meta = resin_prepare(before_mesh, printer, target_thickness_mm)
    if not meta.get("changed"):
        return {"changed": False, "before": before, "after": before, "actions": [], "preparation": meta, "validation_error": None}
    write_binary_stl(target, prepared)
    persisted_mesh = load_mesh(target)
    after = analyse_mesh(persisted_mesh)
    bm, am = before.get("metrics", {}), after.get("metrics", {})
    regressions = []
    if int(am.get("boundary_edges") or 0) > int(bm.get("boundary_edges") or 0): regressions.append("open boundary count increased")
    if int(am.get("nonmanifold_edges") or 0) > int(bm.get("nonmanifold_edges") or 0): regressions.append("non-manifold edge count increased")
    if int(am.get("duplicate_faces") or 0) > int(bm.get("duplicate_faces") or 0): regressions.append("duplicate face count increased")
    if bool(bm.get("watertight")) and not bool(am.get("watertight")): regressions.append("a watertight source became open")
    if regressions:
        target.unlink(missing_ok=True)
        return {"changed": False, "before": before, "after": before, "actions": [], "preparation": meta, "validation_error": "Resin Preparation rejected the candidate because " + ", ".join(regressions) + ". The original was left unchanged."}
    return {"changed": True, "before": before, "after": after, "actions": meta.get("actions") or [], "preparation": meta, "validation_error": None}
