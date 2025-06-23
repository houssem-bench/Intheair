# 📍 Cadastre Extractor

A web-based Streamlit application for extracting French **cadastre parcels** from **DXF** or **KML** files. It identifies land parcel information by analyzing geographical shapes from uploaded CAD or GIS files and querying the French IGN cadastre API.

---

## ✨ Features

- 🗂 Supports **DXF** (AutoCAD) and **KML** (Google Earth) files
- 📐 Auto-detects Coordinate Reference System (CRS) using geospatial heuristics
- 🌍 Reprojects geometries to WGS84 (`EPSG:4326`)
- 📦 Queries **IGN Cadastre API** using geometry for parcel retrieval
- 🧾 Displays list of parcel `sections` and `numbers`
- 🔁 Handles `MultiPolygon` features in KML
- ⚡ Optimized using multi-threaded parallelism
- 💾 Temporary file management and secure cleanup

---
