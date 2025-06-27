# 🏗️ DXF Talus Trimming & Courbe Cleaning Tool

This tool processes a DXF file containing **topographic lines**, **building outlines**, and **talus (slope) indicators**, then performs advanced spatial operations to **clean and trim courbe lines** based on:

- Paired talus lines
- Building geometries
- Generated terrain "strips"

⚡ Designed for high performance using multithreading.

---

## 📁 Features

✅ **Supports multiple courbe layers**:  
- `COURBES_DE_NIVEAU_PRINCIPALES`  
- `COURBES_DE_NIVEAU_INTERMEDIAIRES`  
- `COURBES_DE_NIVEAU_SECONDAIRES`

✅ **Automatically detects and pairs talus lines** (`BAS_TALUS`, `HAUT_TALUS`)  
✅ **Generates polygonal strips between talus lines**  
✅ **Removes courbes inside buildings and strips**  
✅ **Trims courbes using buffered talus masks**  
✅ **Optimized with parallel processing (CPU)**  
✅ **Produces a clean DXF with only useful courbes**

---

## 🚀 How It Works

1. **Extract Geometry**  
   From DXF layers: buildings, courbes, talus.

2. **Pair Talus Lines**  
   Using midpoint proximity + KDTree.

3. **Generate Strips**  
   Polygon areas between paired talus lines.

4. **Trim Courbes**  
   - Remove parts inside buildings
   - Remove parts inside strips
   - Cut around buffered talus areas

5. **Save Final Result**  
   Overwrites the original courbes in a clean DXF.


