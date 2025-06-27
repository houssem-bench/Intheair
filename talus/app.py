import os
import ezdxf
import numpy as np
import tempfile
import streamlit as st
import time
from shapely.geometry import LineString, Polygon, MultiPolygon, MultiLineString
from shapely.ops import unary_union, snap
from concurrent.futures import ThreadPoolExecutor
from scipy.spatial import cKDTree
from typing import List, Union, Optional
from batiment import extract_building_geometries, consolidate_buildings,remove_courbes_inside_buildings
from talus import (
    extract_talus_lines,
    pair_talus_lines,
    create_talus_strips,
    remove_courbes_inside_strips,
    trim_courbes_by_talus,
    extract_specific_lines
)
# Constants
BUFFER_DISTANCE = 3.0
DEFAULT_MAX_PAIR_DISTANCE = 13.8
COURBE_LAYERS = [
    "COURBES_DE_NIVEAU_PRINCIPALES",
    "COURBES_DE_NIVEAU_INTERMEDIAIRES",
    "COURBES_DE_NIVEAU_SECONDAIRES"
]
max_pair_distance = DEFAULT_MAX_PAIR_DISTANCE

st.set_page_config(page_title="Talus Trimming DXF Processor", layout="wide")
st.title("📐 Talus Trimming & Courbe Processor")

uploaded_file = st.file_uploader("📤 Upload a DXF file", type=["dxf"])

if uploaded_file:
    st.success("✅ File uploaded. Beginning processing...")

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "uploaded.dxf")
        with open(input_path, "wb") as f:
            f.write(uploaded_file.read())

        try:
            start_time = time.time()
            doc = ezdxf.readfile(input_path)
            msp = doc.modelspace()

            # Step 1: Extract + process buildings
            building_geoms = extract_building_geometries(msp)
            consolidated_buildings = consolidate_buildings(building_geoms, buffer_distance=3.2)

            # Step 2: Process talus lines
            bas_talus, haut_talus = extract_talus_lines(msp)
            pairs = pair_talus_lines(bas_talus, haut_talus, max_pair_distance)
            strips, skipped = create_talus_strips(pairs)

            # Step 3: Extract courbes
            original_courbes = extract_specific_lines(msp, COURBE_LAYERS)
            trimmed_courbes = {}

            for layer_name in COURBE_LAYERS:
                courbe_lines = original_courbes.get(layer_name, [])
                if consolidated_buildings:
                    courbe_lines = remove_courbes_inside_buildings(courbe_lines, consolidated_buildings)
                courbe_lines = remove_courbes_inside_strips(courbe_lines, strips)
                courbe_lines = trim_courbes_by_talus(courbe_lines, haut_talus, bas_talus)
                trimmed_courbes[layer_name] = courbe_lines

            # Step 4: Modify DXF content
            entities_to_remove = [e for e in msp if e.dxf.layer in COURBE_LAYERS]
            for entity in entities_to_remove:
                msp.delete_entity(entity)

            for layer_name, lines in trimmed_courbes.items():
                for line in lines:
                    msp.add_lwpolyline(list(line.coords), dxfattribs={
                        'layer': layer_name,
                        'color': 2,
                        'linetype': 'CONTINUOUS'
                    })

            # Step 5: Save the final output
            final_path = os.path.join(tmpdir, "final_output.dxf")
            doc.saveas(final_path)

            st.success(f"🎉 Processing complete in {time.time() - start_time:.2f}s")
            with open(final_path, "rb") as f:
                st.download_button("⬇️ Download Processed DXF", f.read(), file_name="trimmed_output.dxf")

        except Exception as e:
            st.error(f"❌ Processing failed: {e}")
