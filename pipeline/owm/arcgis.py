"""Download every feature of an ArcGIS REST layer to a gzipped CSV.

    python -m owm.arcgis https://host/arcgis/rest/services/.../MapServer/0 out.csv.gz

Points are written as X/Y in WGS84 (outSR=4326); polygons/lines use their
first vertex. Pages by objectId ranges, which works whether or not the
server supports resultOffset paging. Stdlib only.
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
import time
import urllib.parse
import urllib.request


def _get(url: str, params: dict, tries: int = 4) -> dict:
    q = url + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            req = urllib.request.Request(q, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) orphaned-well-map/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 ** (i + 1))


def _xy(geom: dict | None):
    if not geom:
        return "", ""
    if "x" in geom:
        return geom["x"], geom["y"]
    for key in ("points", "paths", "rings"):
        if geom.get(key):
            first = geom[key][0]
            pt = first if key == "points" else first[0]
            return pt[0], pt[1]
    return "", ""


def download(layer: str, dst: str, where: str = "1=1", batch: int | None = None) -> int:
    meta = _get(layer, {"f": "json"})
    oid_field = meta.get("objectIdField") or next(
        (f["name"] for f in meta.get("fields", []) if f.get("type") == "esriFieldTypeOID"), "OBJECTID")
    batch = batch or min(int(meta.get("maxRecordCount") or 1000), 2000)
    ids = _get(layer + "/query", {"where": where, "returnIdsOnly": "true", "f": "json"}).get("objectIds") or []
    ids.sort()
    names: list[str] | None = None
    n = 0
    with gzip.open(dst, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for i in range(0, len(ids), batch):
            chunk = ids[i:i + batch]
            d = _get(layer + "/query", {
                "where": f"{oid_field} >= {chunk[0]} AND {oid_field} <= {chunk[-1]}",
                "outFields": "*", "outSR": "4326", "returnGeometry": "true", "f": "json"})
            for feat in d.get("features", []):
                attrs = feat.get("attributes") or {}
                if names is None:
                    names = list(attrs)
                    w.writerow(["X", "Y"] + names)
                x, y = _xy(feat.get("geometry"))
                w.writerow([x, y] + ["" if attrs.get(k) is None else attrs.get(k) for k in names])
                n += 1
    if n != len(ids):
        print(f"warning: {layer}: {n} features written, {len(ids)} ids reported", file=sys.stderr)
    return n


if __name__ == "__main__":
    # optional filter: "<layer url>|<where clause>"
    layer, _, where = sys.argv[1].partition("|")
    print(download(layer, sys.argv[2], where or "1=1"), "features")
