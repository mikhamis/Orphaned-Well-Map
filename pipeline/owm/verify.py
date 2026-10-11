"""Cross-check joined operators against an agency source other than the joined file.

    python -m owm.verify ok-orphan-list OK_orphan-well-list.xlsx ../site/data
    python -m owm.verify ky-kgs-reports DIR_OF_KGS_WELL_REPORT_HTML ../site/data

Prints a JSON summary to paste into the state's config under "verification".
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import re
from datetime import date
from pathlib import Path

from .util import haversine_m


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _load(data: Path, code: str):
    m = json.loads((data / "manifest.json").read_text())
    st = next(s for s in m["states"] if s["code"] == code)
    rows = json.loads((data / "states" / f"{code}.json").read_text())
    return m, st, rows, json.loads((data / "points.json").read_text())


def ok_orphan_list(xlsx: Path, data: Path) -> dict:
    """OCC orphan well list (separate OCC publication) vs operator joined from RBDMS."""
    import openpyxl  # only needed for this check

    ws = openpyxl.load_workbook(xlsx, read_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True)
    hdr = next(it)
    occ = {}
    for r in it:
        d = dict(zip(hdr, r))
        api = str(d.get("API") or "").strip()[:10]
        if api:
            occ[api] = (d.get("OperatorName") or "").strip()
    _, _, rows, _ = _load(data, "OK")
    on_list = same = 0
    diffs = []
    for d in rows:
        api = (d.get("sa") or d.get("id") or "")[:10]
        if api not in occ:
            continue
        on_list += 1
        if _norm(occ[api]) == _norm(d.get("op")):
            same += 1
        else:
            diffs.append([api, occ[api], d.get("op")])
    return {
        "date": date.today().isoformat(),
        "method": "Compared the operator joined from RBDMS with the operator on the OCC Orphan Well List "
                  "(orphan-well-list.xlsx), for every USGS Oklahoma well that appears on that list.",
        "checked": on_list, "agree": same, "of_usgs_wells": len(rows),
        "differences": diffs[:20],
    }


def ky_kgs_reports(report_dir: Path, data: Path) -> dict:
    """Random sample of KGS per-well report pages vs permit, operator, and location on the map."""
    _, st, rows, pts = _load(data, "KY")
    idx = {d["id"]: i for i, d in enumerate(rows)}

    def field(x, name):
        r = re.search(re.escape(name) + r":\s*\|[\s|]*([^|]+?)\s*\|", x)
        return r.group(1).strip() if r else None

    checked = agree = 0
    loc_gaps = []
    diffs = []
    for f in sorted(glob.glob(str(report_dir / "KYcheck_*.html"))):
        pid = Path(f).stem.split("_", 1)[1]
        t = re.sub(r"<script.*?</script>|<style.*?</style>", "", Path(f).read_text(errors="replace"), flags=re.S)
        x = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " | ", t)))
        permit, op, ll = field(x, "Permit Number"), field(x, "Operator"), field(x, "Lat, Lon (NAD 83)")
        if pid not in idx or not permit:
            continue
        i = idx[pid]
        d, g = rows[i], st["offset"] + i
        checked += 1
        ok = permit.lstrip("0") == pid.lstrip("0") and _norm(op) == _norm(d.get("op"))
        agree += ok
        if not ok:
            diffs.append([pid, permit, op, d.get("op")])
        if ll:
            lat, lon = map(float, ll.split(","))
            loc_gaps.append(round(haversine_m(lon, lat, pts["lon"][g], pts["lat"][g])))
    return {
        "date": date.today().isoformat(),
        "method": "Random sample of matched wells looked up on the KGS online well report "
                  "(kgs.uky.edu/kygeode/services/oilgas/wellReport.asp); compared permit number and operator. "
                  "The report reads from the same KGS database as the joined file, so this confirms the join, not KGS's records.",
        "checked": checked, "agree": agree,
        "location_gaps_over_100m": sum(1 for gdist in loc_gaps if gdist > 100),
        "differences": diffs,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("check", choices=["ok-orphan-list", "ky-kgs-reports"])
    ap.add_argument("source")
    ap.add_argument("data")
    a = ap.parse_args(argv)
    fn = ok_orphan_list if a.check == "ok-orphan-list" else ky_kgs_reports
    print(json.dumps(fn(Path(a.source), Path(a.data)), indent=2))


if __name__ == "__main__":
    main()
