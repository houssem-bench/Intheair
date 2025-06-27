import os
import ezdxf
import numpy as np
import argparse
import matplotlib.pyplot as plt
from shapely.geometry import LineString, Polygon, GeometryCollection, MultiLineString, MultiPolygon
from shapely.ops import unary_union, snap, polygonize
from shapely.validation import explain_validity
from scipy.spatial import cKDTree
from typing import List, Tuple, Optional, Union
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from concurrent.futures import ProcessPoolExecutor
import time

def buffer_building_geom(geom, buffer_distance):
    try:
        if geom.geom_type == 'LineString':
            return geom.buffer(buffer_distance / 2, cap_style=2)
        elif geom.geom_type == 'Polygon':
            return geom.buffer(buffer_distance, cap_style=2)
    except Exception as e:
        print(f"❌ Buffering error: {e}")
    return None

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

def remove_courbes_inside_buildings(courbes: List[LineString], buildings: Union[Polygon, MultiPolygon]) -> List[LineString]:
    """Cut parts of courbes that intersect buildings."""
    if not courbes or not buildings:
        return courbes

    mask = buildings if isinstance(buildings, (Polygon, MultiPolygon)) else unary_union(buildings)
    trimmed = []

    for line in courbes:
        if line.intersects(mask):
            result = line.difference(mask)
            if result.is_empty:
                continue
            if result.geom_type == "LineString":
                trimmed.append(result)
            elif result.geom_type == "MultiLineString":
                trimmed.extend(result.geoms)
        else:
            trimmed.append(line)

    print(f"🏛️ Trimmed courbes against buildings: {len(courbes)} → {len(trimmed)}")
    return trimmed


def extract_building_geometries(msp: ezdxf.layouts.Modelspace) -> List[Union[LineString, Polygon]]:
    """Extract all building elements from modelspace."""
    building_geoms = []
    building_layers = {'batiment', 'bâtiment', 'building'}
    
    for entity in msp:
        try:
            layer = entity.dxf.layer.lower()
            if not any(b in layer for b in building_layers):
                continue
                
            geom = extract_line(entity)
            if geom is None:
                continue
                
            # Handle closed polylines as polygons
            if entity.dxftype() in ['LWPOLYLINE', 'POLYLINE']:
                is_closed = entity.closed if entity.dxftype() == 'LWPOLYLINE' else entity.is_closed
                if is_closed and len(geom.coords) >= 3:
                    poly = Polygon(geom.coords)
                    if poly.is_valid:
                        building_geoms.append(poly)
                        continue
            
            building_geoms.append(geom)
            
        except Exception as e:
            print(f"Error processing building entity on layer {entity.dxf.layer}: {e}")

    print(f"Extracted {len(building_geoms)} building geometries")
    return building_geoms


def consolidate_buildings(building_geoms: List[Union[LineString, Polygon]], buffer_distance: float = 3.2) -> Optional[MultiPolygon]:
    if not building_geoms:
        return None

    buffer_fn = partial(buffer_building_geom, buffer_distance=buffer_distance)

    with ProcessPoolExecutor() as executor:
        buffered = list(filter(None, executor.map(buffer_fn, building_geoms)))

    if not buffered:
        return None

    try:
        combined = unary_union([g for g in buffered if g.is_valid])
        if combined.geom_type == 'Polygon':
            return MultiPolygon([combined])
        elif combined.geom_type == 'MultiPolygon':
            return combined
    except Exception as e:
        print(f"❌ Error combining buildings: {e}")

    return None
