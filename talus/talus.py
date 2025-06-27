import os
import ezdxf
import numpy as np
import argparse
import matplotlib.pyplot as plt
from shapely.geometry import LineString, Polygon, GeometryCollection, MultiLineString, MultiPolygon
from shapely.ops import unary_union, snap, polygonize
from shapely.validation import explain_validity
from scipy.spatial import cKDTree
from shapely.strtree import STRtree
from typing import List, Tuple, Optional, Union
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import time

def process_talus_pair(idx_pair, num_points=20, area_threshold=1e-4, snap_tol=0.01):
    from shapely.geometry import LineString, Polygon
    from shapely.ops import snap

    idx, (base, top) = idx_pair
    try:
        def interpolate_line(line, num=50):
            if line.length == 0:
                return [line.coords[0]] * num
            return [line.interpolate(i / (num - 1), normalized=True).coords[0] for i in range(num)]

        def should_reverse(base_coords, top_coords):
            from shapely.geometry import Point
            d1 = Point(base_coords[0]).distance(Point(top_coords[0]))
            d2 = Point(base_coords[-1]).distance(Point(top_coords[0]))
            return d2 < d1

        base_coords = interpolate_line(base, num_points)
        top_coords = interpolate_line(top, num_points)

        if should_reverse(base_coords, top_coords):
            top_coords = top_coords[::-1]

        base_line = LineString(base_coords)
        top_line = snap(LineString(top_coords), base_line, snap_tol)

        loop = list(base_line.coords) + list(top_line.coords)[::-1]
        if loop[0] != loop[-1]:
            loop.append(loop[0])

        poly = Polygon(loop)
        if not poly.is_valid:
            poly = poly.buffer(0)

        if poly.is_empty:
            return None, idx

        if poly.geom_type == "Polygon" and poly.area >= area_threshold:
            return poly, None
        elif poly.geom_type == "MultiPolygon":
            valid_polys = [p for p in poly.geoms if p.area >= area_threshold]
            return valid_polys if valid_polys else None, idx

    except Exception:
        return None, idx

    return None, idx

# --- Configuration ---
DEFAULT_INPUT_DXF = "TEST.dxf"
DEFAULT_OUTPUT_FOLDER = "visualizations2"
DEFAULT_MAX_PAIR_DISTANCE = 13.8
DEFAULT_STRIP_RESOLUTION = 50
BUFFER_DISTANCE = 3.0
COURBE_LAYERS = [
    "COURBES_DE_NIVEAU_PRINCIPALES",
    "COURBES_DE_NIVEAU_INTERMEDIAIRES", 
    "COURBES_DE_NIVEAU_SECONDAIRES"
]

def timer_decorator(func):
    """Decorator to measure function execution time"""
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"⏱️ {func.__name__} executed in {end-start:.2f}s")
        return result
    return wrapper



def extract_specific_lines(msp, layer_names):
    """Extract lines from specific layers with exact name matching"""
    layer_data = {name: [] for name in layer_names}
    
    for entity in msp:
        if entity.dxf.layer in layer_names:
            try:
                if entity.dxftype() == "LWPOLYLINE":
                    points = list(entity.get_points('xy'))
                elif entity.dxftype() == "POLYLINE":
                    points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
                elif entity.dxftype() == "LINE":
                    points = [(entity.dxf.start.x, entity.dxf.start.y),
                              (entity.dxf.end.x, entity.dxf.end.y)]
                
                if len(points) >= 2:
                    layer_data[entity.dxf.layer].append(LineString(points))
            except Exception as e:
                print(f"⚠️ Error processing entity in layer {entity.dxf.layer}: {e}")
    
    for layer, lines in layer_data.items():
        print(f"✅ Extracted {len(lines)} lines from layer {layer}")
    
    return layer_data


def extract_line(entity):
    """Convert DXF entity to Shapely LineString if valid."""
    try:
        if entity.dxftype() == "LWPOLYLINE":
            points = list(entity.get_points('xy'))
        elif entity.dxftype() == "POLYLINE":
            points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        elif entity.dxftype() == "LINE":
            points = [(entity.dxf.start.x, entity.dxf.start.y),
                      (entity.dxf.end.x, entity.dxf.end.y)]
        else:
            return None
        return LineString(points) if len(points) >= 2 else None
    except Exception as e:
        print(f"⚠️ Failed to extract line from entity: {e}")
        return None


def extract_talus_lines(msp):
    bas_talus, haut_talus = [], []
    for entity in msp:
        line = extract_line(entity)
        if not line:
            continue
        layer = entity.dxf.layer.lower()
        if "bas_talus" in layer:
            bas_talus.append(line)
        elif "haut_talus" in layer:
            haut_talus.append(line)
    print(f"✅ Extracted {len(bas_talus)} BAS_TALUS and {len(haut_talus)} HAUT_TALUS lines")
    return bas_talus, haut_talus


def interpolate_line(line, num=50):
    """Resample line to a fixed number of points."""
    if line.length == 0:
        return [line.coords[0]] * num
    return [line.interpolate(i / (num - 1), normalized=True).coords[0] for i in range(num)]

def should_reverse(base_coords, top_coords):
    """Ensure both lines are oriented similarly."""
    from shapely.geometry import Point
    d1 = Point(base_coords[0]).distance(Point(top_coords[0]))
    d2 = Point(base_coords[-1]).distance(Point(top_coords[0]))
    return d2 < d1


def pair_talus_lines(bas_talus, haut_talus, max_pair_distance):
    if not bas_talus or not haut_talus:
        print("⚠️ Missing talus lines for pairing")
        return []

    bas_points = [line.interpolate(0.5, normalized=True).coords[0] for line in bas_talus if not line.is_empty]
    haut_points = [line.interpolate(0.5, normalized=True).coords[0] for line in haut_talus if not line.is_empty]

    if not bas_points or not haut_points:
        return []

    bas_array = np.array(bas_points)
    haut_array = np.array(haut_points)

    tree = cKDTree(haut_array)
    distances, indices = tree.query(bas_array, k=1)

    pairs = [(bas_talus[i], haut_talus[indices[i]]) for i in range(len(distances)) if distances[i] <= max_pair_distance]

    print(f"✅ Successfully paired {len(pairs)}/{len(bas_talus)} talus lines")
    return pairs


def create_talus_strips(pairs, num_points=20, area_threshold=1e-4, snap_tol=0.01):
    strips = []
    skipped_indices = []

    func = partial(process_talus_pair, num_points=num_points, area_threshold=area_threshold, snap_tol=snap_tol)

    with ProcessPoolExecutor() as executor:
        results = executor.map(func, enumerate(pairs))

    for result, idx in results:
        if result:
            strips.extend(result if isinstance(result, list) else [result])
        elif idx is not None:
            skipped_indices.append(idx)

    print(f"🎉 Done: {len(strips)} strips created | ❌ {len(skipped_indices)} skipped")
    return strips, skipped_indices

def remove_courbes_inside_strips(courbes, strips, batch_size=100):
    if not strips or not courbes:
        return courbes

    mask = unary_union(strips)
    trimmed = []

    def process_batch(batch):
        results = []
        for line in batch:
            if line.intersects(mask):
                result = line.difference(mask)
                if result.is_empty:
                    continue
                if isinstance(result, LineString):
                    results.append(result)
                elif isinstance(result, MultiLineString):
                    results.extend(result.geoms)
            else:
                results.append(line)
        return results

    # Avoid threading if small
    if len(courbes) <= batch_size:
        trimmed = process_batch(courbes)
    else:
        batches = [courbes[i:i+batch_size] for i in range(0, len(courbes), batch_size)]
        with ThreadPoolExecutor() as executor:
            results = executor.map(process_batch, batches)
        for sublist in results:
            trimmed.extend(sublist)

    print(f"✅ Trimmed courbes: {len(courbes)} → {len(trimmed)}")
    return trimmed

def trim_courbes_by_talus(courbes, haut_talus, bas_talus, buffer_dist=3):
    if not courbes:
        return []

    talus_lines = [l for l in haut_talus + bas_talus if l.length > 0.1]
    talus_buffers = [l.buffer(buffer_dist, cap_style=2) for l in talus_lines]

    mask = unary_union(talus_buffers)
    trimmed = []

    for line in courbes:
        diff = line.difference(mask)
        if diff.is_empty:
            continue
        elif isinstance(diff, LineString):
            trimmed.append(diff)
        elif isinstance(diff, MultiLineString):
            trimmed.extend(diff.geoms)

    print(f"🪚 Trimmed courbes using merged talus mask: {len(courbes)} → {len(trimmed)}")
    return trimmed

