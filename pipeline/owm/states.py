"""Per-state well records, described by JSON configs in pipeline/states/.

Every state publishes well data differently, so each config maps that
state's file onto one schema. See pipeline/states/README.md.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .util import is_placeholder_operator, normalize_api, normalize_id, parse_float, read_table, valid_lonlat

FIELDS = ("api", "id", "operator", "status", "lat", "lon", "lease", "well_name", "date")


@dataclass
class StateWell:
    api: str | None
    alt_id: str | None
    operator: str
    status: str
    lon: float | None
    lat: float | None
    lease: str
    well_name: str
    date: str
    active: bool
    extra: dict | None = None   # columns named by "where" rules, raw strings

    @property
    def has_location(self) -> bool:
        return valid_lonlat(self.lon, self.lat)


def load_configs(states_dir: Path) -> dict[str, dict]:
    out = {}
    for p in sorted(Path(states_dir).glob("*.json")):
        if p.name.startswith("_"):
            continue
        cfg = json.loads(p.read_text())
        code = cfg["state"].upper()
        if p.stem.upper() != code:
            raise SystemExit(f"{p}: file name must match state code {code}")
        cfg["_path"] = str(p)
        out[code] = cfg
    return out


def fetch(cfg: dict, cache_dir: Path, local_file: Path | None = None) -> Path | None:
    """Return a path to the state's table, downloading into cache_dir if needed."""
    if local_file:
        return Path(local_file)
    src = cfg.get("source") or {}
    if src.get("arcgis"):
        from .arcgis import download
        cache_dir.mkdir(parents=True, exist_ok=True)
        dest = cache_dir / f"{cfg['state'].upper()}_arcgis.csv.gz"
        if not dest.exists():
            layers = src["arcgis"] if isinstance(src["arcgis"], list) else [src["arcgis"]]
            if len(layers) == 1:
                # "arcgis_mirrors": other URLs serving the same layer, tried in order on failure
                for i, url in enumerate([layers[0]] + list(src.get("arcgis_mirrors") or [])):
                    try:
                        download(url, str(dest))
                        break
                    except Exception as e:
                        if i == len(src.get("arcgis_mirrors") or []):
                            raise
                        print(f"{cfg['state']}: {url} failed ({e}); trying mirror", file=sys.stderr)
            else:  # several layers with the same schema (e.g. one per well type): concatenate
                import csv
                import gzip
                parts = []
                for i, layer in enumerate(layers):
                    part = cache_dir / f"{cfg['state'].upper()}_arcgis_{i}.csv.gz"
                    download(layer, str(part))
                    parts.append(part)
                with gzip.open(dest, "wt", newline="", encoding="utf-8") as out:
                    w = None
                    for part in parts:
                        for row in csv.DictReader(gzip.open(part, "rt", newline="", encoding="utf-8")):
                            if w is None:
                                w = csv.DictWriter(out, fieldnames=list(row), extrasaction="ignore")
                                w.writeheader()
                            w.writerow(row)
        return dest
    url = src.get("url")
    if not url:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    fname = cfg["state"].upper() + "_" + re.sub(r"[^A-Za-z0-9._-]", "_", url.rsplit("/", 1)[-1] or "data")
    dest = cache_dir / fname
    if not dest.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "orphaned-well-map/1.0"})
        with urllib.request.urlopen(req, timeout=600) as r, open(dest.with_suffix(".part"), "wb") as f:
            shutil.copyfileobj(r, f)
        dest.with_suffix(".part").rename(dest)
    if zipfile.is_zipfile(dest):
        member = src.get("member")
        with zipfile.ZipFile(dest) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            if member is None:
                tables = [n for n in names if n.lower().endswith((".csv", ".txt", ".geojson", ".tsv", ".xlsx"))]
                if len(tables) != 1:
                    raise SystemExit(f"{cfg['state']}: set source.member; zip contains {names[:20]}")
                member = tables[0]
            out = cache_dir / (dest.stem + "__" + Path(member).name)
            if not out.exists():
                with z.open(member) as zf, open(out, "wb") as f:
                    shutil.copyfileobj(zf, f)
            return out
    return dest


def load_records(cfg: dict, path: Path) -> tuple[list[StateWell], dict]:
    cols = cfg["columns"]
    if not (cols.get("api") or cols.get("id")):
        raise SystemExit(f"{cfg['state']}: columns.api or columns.id is required")
    src = cfg.get("source") or {}
    active_res = [re.compile(p, re.I) for p in cfg.get("active_status", [])]
    active_where = cfg.get("active_where") or []
    risk_where = (cfg.get("at_risk") or {}).get("where") or []
    extra_cols = sorted({c["column"] for c in active_where + risk_where})
    st = cfg["state"].upper()
    out: list[StateWell] = []
    stats = {"rows": 0, "no_api": 0, "active": 0}
    checked = False
    for row in read_table(path, encoding=src.get("encoding", "utf-8-sig"), delimiter=src.get("delimiter")):
        if not checked:
            missing = [c for k, c in cols.items() if c and c not in row] + [c for c in extra_cols if c not in row]
            if missing:
                raise SystemExit(f"{st}: columns {missing} not in file. Headers: {list(row.keys())}")
            checked = True
        stats["rows"] += 1

        def g(k):
            c = cols.get(k)
            return (row.get(c) or "").strip() if c else ""

        api = normalize_api(g("api"), st)
        if api is None:
            stats["no_api"] += 1
        status = g("status")
        extra = {c: (row.get(c) or "").strip() for c in extra_cols} if extra_cols else None
        if active_where:
            active = where(extra, active_where)
        else:
            active = bool(status) and any(r.search(status) for r in active_res)
        stats["active"] += active
        out.append(StateWell(
            api=api, alt_id=normalize_id(g("id")), operator=g("operator"), status=status,
            lon=parse_float(g("lon")), lat=parse_float(g("lat")),
            lease=g("lease"), well_name=g("well_name"), date=g("date"), active=active, extra=extra,
        ))
    return out, stats


def where(extra: dict | None, rules: list[dict]) -> bool:
    """All rules must hold. Rule keys: column, plus one of
    empty (bool), lte / gte (compared as strings, so use same-width values such
    as years), match (regex)."""
    extra = extra or {}
    for r in rules:
        v = extra.get(r["column"], "")
        if "empty" in r and (v == "") != r["empty"]:
            return False
        if "lte" in r and not (v and v <= r["lte"]):
            return False
        if "gte" in r and not (v and v >= r["gte"]):
            return False
        if "match" in r and not re.search(r["match"], v, re.I):
            return False
    return True


def latest_by_api(records: list[StateWell], key: str = "api") -> dict[str, StateWell]:
    """One record per API (or ``key``): prefer a real operator name, then the latest date.

    Dates are compared as normalized strings, so configs should point
    ``date`` at an ISO-like (YYYY-MM-DD) column where one exists.
    """
    best: dict[str, StateWell] = {}
    for r in records:
        k = getattr(r, key)
        if k is None:
            continue
        cur = best.get(k)
        if cur is None or _rank(r) >= _rank(cur):
            best[k] = r
    return best


def _rank(r: StateWell):
    return (not is_placeholder_operator(r.operator), _iso(r.date))


def _iso(d: str) -> str:
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", d or "")
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return d or ""
