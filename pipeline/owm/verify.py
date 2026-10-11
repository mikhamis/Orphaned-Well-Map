"""Cross-check joined operators against an agency source other than the joined file.

    python -m owm.verify ok-orphan-list OK_orphan-well-list.xlsx ../site/data
    python -m owm.verify ky-kgs-reports DIR_OF_KGS_WELL_REPORT_HTML ../site/data
    python -m owm.verify pa-dep-report PA_abandoned_orphan.csv ../site/data
    python -m owm.verify ny-orphan-list NY_orphaned.csv ../site/data

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


def _compare(code: str, ref: dict, data: Path, method: str) -> dict:
    _, _, rows, _ = _load(data, code)
    checked = agree = 0
    diffs = []
    for d in rows:
        api = (d.get("sa") or d.get("id") or "")[:10]
        if api in ref and d.get("op") is not None:
            checked += 1
            if _norm(ref[api]) == _norm(d["op"]):
                agree += 1
            else:
                diffs.append([api, ref[api], d["op"]])
    return {"date": date.today().isoformat(), "method": method, "checked": checked, "agree": agree,
            "of_usgs_wells": len(rows), "differences": diffs[:20]}


def _api_map(path: Path, api_col: str, op_col: str, state: str) -> dict:
    from .util import normalize_api, read_table
    out = {}
    for r in read_table(path):
        a = normalize_api(r.get(api_col), state)
        if a:
            out[a] = r.get(op_col) or ""
    return out


def pa_dep_report(csv_path: Path, data: Path) -> dict:
    """DEP Abandoned and Orphan Wells report (SSRS export) vs PASDA well layer operator."""
    return _compare("PA", _api_map(csv_path, "API", "OPERATOR", "PA"), data,
                    "Compared the operator joined from DEP's statewide well layer (PASDA) with the operator on DEP's "
                    "separate Abandoned and Orphan Wells report (cedatareporting.pa.gov), for every USGS Pennsylvania well on that report.")


def ny_orphan_list(csv_path: Path, data: Path) -> dict:
    """NYSDEC Orphaned Wells dataset vs operator from the full wells dataset."""
    return _compare("NY", _api_map(csv_path, "API WELL NUMBER", "COMPANY NAME", "NY"), data,
                    "Compared the owner joined from NYSDEC's full wells dataset with the owner on NYSDEC's separate "
                    "Orphaned Wells dataset (data.ny.gov vgue-bamz), for every USGS New York well on that list.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("check", choices=["ok-orphan-list", "ky-kgs-reports", "pa-dep-report", "ny-orphan-list"])
    ap.add_argument("source")
    ap.add_argument("data")
    a = ap.parse_args(argv)
    fn = {"ok-orphan-list": ok_orphan_list, "ky-kgs-reports": ky_kgs_reports,
          "pa-dep-report": pa_dep_report, "ny-orphan-list": ny_orphan_list}[a.check]
    print(json.dumps(fn(Path(a.source), Path(a.data)), indent=2))


if __name__ == "__main__":
    main()
