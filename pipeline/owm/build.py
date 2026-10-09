"""Build the static site data.

    python -m owm.build --usgs path/to/dowdb_2026.csv --out ../site/data
    python -m owm.build --inspect path/to/file.csv

Outputs (all JSON):
  manifest.json      build info, per-state summary, operator table
  points.json        columnar lon/lat/state/join/operator for every well
  states/XX.json     per-well detail for one state, in points order
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import states as st_mod
from . import usgs
from .join import JoinParams, join_state
from .util import STATE_NAMES, is_placeholder_operator, normalize_name, read_table, write_json

HERE = Path(__file__).resolve().parent.parent

# join codes used by the front end
J_NO_CONFIG, J_UNMATCHED, J_PLACEHOLDER, J_OPERATOR = 0, 1, 2, 3

_SUFFIX = re.compile(r"\b(inc|llc|l l c|lp|l p|co|corp|corporation|company|ltd|plc|incorporated)\b")


def operator_key(name: str) -> str:
    n = normalize_name(name).replace("&", " and ")
    n = _SUFFIX.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def inspect(path: Path) -> None:
    rows = read_table(path)
    first = next(rows, None)
    if first is None:
        print("empty file")
        return
    print("Columns:")
    for k, v in first.items():
        print(f"  {k!r}: {str(v)[:60]!r}")
    try:
        cols = usgs.detect_columns(first.keys())
        print("\nDetected as USGS columns:", json.dumps(cols, indent=2))
    except SystemExit as e:
        print("\n" + str(e))


def build(args) -> dict:
    out = Path(args.out)
    params = JoinParams(radius_m=args.radius_m, loc_tolerance_m=args.loc_tolerance_m)
    overrides = json.loads(args.usgs_columns) if args.usgs_columns else None
    wells, ustats = usgs.load(Path(args.usgs), overrides)
    print(f"USGS: {ustats['loaded']:,} wells loaded of {ustats['rows']:,} rows "
          f"(bad location {ustats['bad_location']}, bad state {ustats['bad_state']}, no API {ustats['no_api']})",
          file=sys.stderr)

    configs = st_mod.load_configs(Path(args.states_dir))
    local = dict(s.split("=", 1) for s in args.state_file)
    by_state: dict[str, list] = defaultdict(list)
    for w in wells:
        by_state[w.state].append(w)

    state_rows = []
    for code in sorted(by_state):
        orphans = by_state[code]
        cfg = configs.get(code)
        info = {"code": code, "name": STATE_NAMES.get(code, code), "count": len(orphans),
                "configured": False, "verified": False}
        if cfg:
            info.update(verified=bool(cfg.get("verified")),
                        source=(cfg.get("source") or {}).get("name"),
                        source_url=(cfg.get("source") or {}).get("docs_url") or (cfg.get("source") or {}).get("url"))
            path = None
            try:
                path = st_mod.fetch(cfg, Path(args.cache), local.get(code))
            except Exception as e:  # network/HTTP errors: keep building other states
                print(f"{code}: fetch failed: {e}", file=sys.stderr)
                info["error"] = f"fetch failed: {type(e).__name__}"
            if path:
                records, rstats = st_mod.load_records(cfg, path)
                jstats = join_state(orphans, records, params)
                info["configured"] = True
                info["stats"] = {**rstats, **jstats}
                print(f"{code}: {len(orphans):,} orphans, {rstats['rows']:,} state rows -> {jstats}", file=sys.stderr)
            elif "error" not in info:
                info["error"] = "no source URL or --state-file"
        state_rows.append(info)

    # operator table (orphans counted by last operator)
    op_counts: Counter = Counter()
    op_names: dict[str, Counter] = defaultdict(Counter)
    op_states: dict[str, set] = defaultdict(set)
    for w in wells:
        e = w.extra
        if e.get("operator") and not e.get("operator_placeholder"):
            k = operator_key(e["operator"])
            op_counts[k] += 1
            op_names[k][e["operator"]] += 1
            op_states[k].add(w.state)
    op_list = [k for k, _ in op_counts.most_common()]
    op_index = {k: i for i, k in enumerate(op_list)}
    operators = [{"name": op_names[k].most_common(1)[0][0], "count": op_counts[k],
                  "states": sorted(op_states[k])} for k in op_list]

    pts = {"lon": [], "lat": [], "s": [], "j": [], "o": [], "a": []}
    state_codes = [r["code"] for r in state_rows]
    offset = 0
    for si, info in enumerate(state_rows):
        info["offset"] = offset
        detail = []
        for w in by_state[info["code"]]:
            e = w.extra
            if not info["configured"]:
                j = J_NO_CONFIG
            elif not e.get("match"):
                j = J_UNMATCHED
            elif e.get("operator_placeholder"):
                j = J_PLACEHOLDER
            else:
                j = J_OPERATOR
            oi = op_index.get(operator_key(e["operator"]), -1) if j == J_OPERATOR else -1
            pts["lon"].append(round(w.lon, 5))
            pts["lat"].append(round(w.lat, 5))
            pts["s"].append(si)
            pts["j"].append(j)
            pts["o"].append(oi)
            pts["a"].append(min(e.get("nearby_active", 0), 999))
            d = {"id": w.api or w.raw_id, "n": w.name, "t": w.type, "st": w.status,
                 "c": w.county, "so": w.surface_owner, "mo": w.mineral_owner}
            if e.get("match"):
                d.update(m=e["match"], md=e.get("match_dist_m"), sa=e.get("state_api"),
                         op=e.get("operator"), opp=e.get("operator_placeholder"),
                         ss=e.get("state_status"), ls=e.get("lease"))
            if info["configured"]:
                d.update(na=e.get("nearby_active", 0), nn=e.get("nearby", []),
                         no=e.get("nearby_operators", []))
            detail.append({k: v for k, v in d.items() if v not in ("", None, [])})
            offset += 1
        write_json(out / "states" / f"{info['code']}.json", detail)

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "usgs": {
            "title": "United States Documented Orphaned Well Database 2026",
            "doi": "10.5066/P13FHBYG",
            "file": Path(args.usgs).name,
            "rows": ustats["rows"], "loaded": ustats["loaded"],
            "dropped_bad_location": ustats["bad_location"], "dropped_bad_state": ustats["bad_state"],
            "columns": ustats["columns"],
        },
        "params": {"radius_m": params.radius_m, "loc_tolerance_m": params.loc_tolerance_m},
        "states": state_rows,
        "state_codes": state_codes,
        "operators": operators,
        "demo": bool(args.demo),
    }
    write_json(out / "points.json", pts)
    write_json(out / "manifest.json", manifest, compact=False)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usgs", help="USGS DOWDB 2026 table (CSV or GeoJSON)")
    ap.add_argument("--inspect", metavar="FILE", help="print a file's columns and exit")
    ap.add_argument("--usgs-columns", help='JSON overrides, e.g. \'{"api": "API_NUM"}\'')
    ap.add_argument("--states-dir", default=str(HERE / "states"))
    ap.add_argument("--state-file", action="append", default=[], metavar="XX=PATH",
                    help="use a local file for a state instead of downloading")
    ap.add_argument("--cache", default=str(HERE.parent / "data" / "raw"))
    ap.add_argument("--out", default=str(HERE.parent / "site" / "data"))
    ap.add_argument("--radius-m", type=float, default=1609.344)
    ap.add_argument("--loc-tolerance-m", type=float, default=30.0)
    ap.add_argument("--demo", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.inspect:
        return inspect(Path(args.inspect))
    if not args.usgs:
        ap.error("--usgs is required")
    build(args)


if __name__ == "__main__":
    main()
