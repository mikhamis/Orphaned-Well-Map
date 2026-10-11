"""Shapefile -> gzipped CSV with X/Y in WGS84 lon/lat (first point of each shape).

    python -m owm.shp2csv in.shp out.csv.gz   (or in.zip: the largest .shp inside is used)

Pure Python (pyshp + pyproj) so CI and local builds produce identical files.
"""
import csv
import gzip
import sys
import tempfile
import zipfile
from pathlib import Path

import shapefile
from pyproj import CRS, Transformer

src, dst = sys.argv[1], sys.argv[2]
if src.lower().endswith(".zip"):
    z = zipfile.ZipFile(src)
    shp = max((i for i in z.infolist() if i.filename.lower().endswith(".shp")), key=lambda i: i.file_size).filename
    stem = shp[:-4]
    tmp = Path(tempfile.mkdtemp())
    for n in z.namelist():
        if n[: len(stem)] == stem and n.lower()[len(stem):] in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            z.extract(n, tmp)
    src = str(tmp / shp)
crs = CRS.from_wkt(open(src[:-4] + ".prj").read())
tf = None if crs.is_geographic else Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
r = shapefile.Reader(src, encoding="utf-8", encodingErrors="replace")
names = [f[0] for f in r.fields[1:]]
n = 0
with gzip.open(dst, "wt", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["X", "Y"] + names)
    for sr in r.iterShapeRecords():
        pts = sr.shape.points
        if pts:
            x, y = pts[0]
            if tf:
                x, y = tf.transform(x, y)
            x, y = round(x, 6), round(y, 6)
        else:
            x = y = ""
        w.writerow([x, y] + list(sr.record))
        n += 1
print(n, "rows", "reprojected" if tf else "geographic")
