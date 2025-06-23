import streamlit as st
import ezdxf
from shapely.geometry import Polygon
import geopandas as gpd
import json
import requests
import tempfile
import os
from urllib.parse import quote
from pyproj import Transformer
import geopy.distance
import numpy as np
import time
from pathlib import Path
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastkml import kml
from shapely.geometry import shape

# ----------------------------------------
# Configuration
# ----------------------------------------
st.set_page_config(page_title="Cadastre Extractor", layout="wide")

# Constants
common_epsgs = ["2154"] + [f"394{i}" for i in range(2, 10)] + ["32630", "32631"]
france_center = (46.6, 2.2)
OUTPUT_DIR = "C:/cadastre_processing"

# ----------------------------------------
# Utility Functions
# ----------------------------------------
@st.cache_data(show_spinner=False, max_entries=5, ttl=3600)
def guess_crs_from_points(points, sample_size=5):
    if len(points) > sample_size:
        points = points[::max(1, len(points) // sample_size)]

    def calculate_epsg_distance(epsg):
        try:
            transformer = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
            distances = [geopy.distance.distance(transformer.transform(x, y)[::-1], france_center).km for x, y in points]
            return epsg, np.mean(distances)
        except Exception:
            return epsg, float('inf')

    best_epsg = None
    min_avg_distance = float('inf')

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(calculate_epsg_distance, epsg) for epsg in common_epsgs]
        for future in as_completed(futures):
            epsg, avg_dist = future.result()
            if avg_dist < min_avg_distance:
                min_avg_distance = avg_dist
                best_epsg = epsg

    return best_epsg

@st.cache_data(show_spinner=True, max_entries=3)
def extract_borders_from_layer(dxf_path, target_layer="0_EMPRISE"):
    doc = ezdxf.readfile(dxf_path)
    entity = doc.modelspace().query(f'LWPOLYLINE[layer=="{target_layer}"]')[0]
    
    if entity.dxftype() == 'LWPOLYLINE':
        return [[(x, y) for x, y, *_ in entity.get_points()]]
    else:
        return [[(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]]

def save_borders_to_gdf(borders):
    all_points = [pt for border in borders for pt in border]
    best_epsg = guess_crs_from_points(all_points)
    if best_epsg is None:
        raise ValueError("Unable to detect CRS")
    polygons = [Polygon(b) for b in borders if len(b) >= 3]
    gdf = gpd.GeoDataFrame(geometry=polygons, crs=f"EPSG:{best_epsg}")
    return gdf.to_crs("EPSG:4326")

def build_encoded_geom_from_gdf(gdf):
    multi = gdf.unary_union
    geojson_geom = json.dumps(gpd.GeoSeries([multi]).__geo_interface__['features'][0]['geometry'])
    return quote(geojson_geom)

@st.cache_data(ttl=3600, show_spinner=False)
def query_cadastre(geom_encoded):
    url = f"https://apicarto.ign.fr/api/cadastre/parcelle?geom={geom_encoded}&source_ign=PCI"
    try:
        res = requests.get(url, timeout=10)
        return res.json().get("features", []) if res.ok else []
    except requests.exceptions.RequestException:
        return []

def ensure_directory_exists(path):
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o755)
        return True
    except Exception as e:
        st.error(f"Directory error: {str(e)}")
        return False

def process_uploaded_file(uploaded_file):
    try:
        ext = uploaded_file.name.split('.')[-1].lower()
        
        # Create temp file with delete=False
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name  # Store path for later use
        
        try:
            if ext == "dxf":
                borders = extract_borders_from_layer(tmp_path)
                gdf = save_borders_to_gdf(borders)
            if ext == "kml":
                borders = parse_kml_polygons(tmp_path)
                if not borders:
                    raise ValueError("No valid polygons found in KML.")
                
                # Directly create GeoDataFrame from lat/lon
                polygons = [Polygon(b) for b in borders if len(b) >= 3]
                print(f"Parsed {len(polygons)} polygons from KML.")
                gdf = gpd.GeoDataFrame(geometry=polygons, crs="EPSG:4326")

                # Continue with the existing pipeline
                geom_encoded = build_encoded_geom_from_gdf(gdf)
                
                cadastre = query_cadastre(geom_encoded)
                return cadastre

            
        finally:
            # Manual cleanup
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
                
    except Exception as e:
        st.error(f"Processing failed: {str(e)}")
        return None
    
from pykml import parser
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from pykml import parser
from lxml import etree

def parse_kml_polygons(kml_file_path):
    with open(kml_file_path, 'r', encoding='utf-8') as f:
        doc = parser.parse(f).getroot()

    ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    coords_list = []

    placemarks = doc.findall(".//kml:Placemark", namespaces=ns)

    for placemark in placemarks:
        # Single Polygon
        polygons = placemark.findall(".//kml:Polygon", namespaces=ns)

        for poly in polygons:
            coords_elem = poly.find(".//kml:coordinates", namespaces=ns)
            if coords_elem is not None:
                coords_text = coords_elem.text.strip()
                coord_tuples = [
                    tuple(map(float, pt.strip().split(",")[:2]))
                    for pt in coords_text.strip().split()
                ]
                if len(coord_tuples) >= 3:
                    coords_list.append(coord_tuples)

    return coords_list

def strip_leading_zeros(value):
    s = str(value).lstrip("0")
    return s if s != "" else "0"

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def display_results(cadastre):
    if not cadastre:
        st.warning("No cadastre parcels found.")
        return

    st.success(f"✅ Found {len(cadastre)} parcels")

    def get_sections():
        return sorted({strip_leading_zeros(f["properties"].get("section", "")) for f in cadastre})

    def get_numeros():
        return sorted({strip_leading_zeros(f["properties"].get("numero", "")) for f in cadastre},
                      key=lambda x: int(x) if x.isdigit() else float('inf'))

    with ThreadPoolExecutor() as executor:
        sections_future = executor.submit(get_sections)
        numeros_future = executor.submit(get_numeros)
        sections = sections_future.result()
        numeros = numeros_future.result()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Sections")
        for chunk in chunks(sections, 6):
            st.markdown(' '.join(f'<span class="badge">{s}</span>' for s in chunk), unsafe_allow_html=True)
    with col2:
        st.markdown("### Numeros")
        for chunk in chunks(numeros, 6):
            st.markdown(' '.join(f'<span class="badge">{n}</span>' for n in chunk), unsafe_allow_html=True)

def main():
    st.title("📍 Extract Cadastre Parcels from DXF")

    st.markdown("""
        <style>
        .badge {
            display: inline-block;
            background-color: #4CAF50;
            color: white;
            padding: 5px 10px;
            margin: 2px;
            border-radius: 12px;
            font-size: 14px;
        }
        </style>
    """, unsafe_allow_html=True)

    uploaded_file = st.file_uploader("Upload a DXF or KML file", type=["dxf", "kml"])

    process_btn = st.button("🔍 Process File")

    if uploaded_file and process_btn:
        if not ensure_directory_exists(OUTPUT_DIR):
            st.stop()

        try:
            with st.spinner("Processing..."):
                start_time = time.time()

                with st.status("Processing steps:", expanded=True) as status:
                    st.write("1. Uploading and preparing file...")
                    cadastre = process_uploaded_file(uploaded_file)

                    st.write("2. Analyzing results...")
                    elapsed = time.time() - start_time
                    st.write(f"3. Completed in {elapsed:.2f} seconds")
                    status.update(label="Processing complete!", state="complete")

                display_results(cadastre)

        except Exception as e:
            st.error(f"Processing failed: {str(e)}")

if __name__ == "__main__":
    main()
