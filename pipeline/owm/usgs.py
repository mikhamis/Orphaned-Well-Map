"""Load the USGS Documented Orphaned Well Database (DOWDB) 2026 release.

Release: U.S. Geological Survey, "United States Documented Orphaned Well
Database 2026", https://doi.org/10.5066/P13FHBYG (supersedes Grove & Merrill
2022, https://doi.org/10.5066/P91PJETI).

The exact column names of the 2026 file were not verifiable when this was
written, so columns are detected from a list of likely spellings. Run
``python -m owm.build --inspect FILE`` to see what was detected, and pass
``--usgs-columns '{"api": "My Column"}'`` to override.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .util import find_column, normalize_api, parse_float, read_table, state_code, valid_lonlat

CANDIDATES = {
    "api": ["API", "API Number", "API_Number", "API_NUM", "APINumber", "API_No", "API14", "API12", "API10", "UWI"],
    "well_id": ["Well ID", "Well_ID", "WellID", "ID Number", "Permit", "Permit Number", "Well Number"],
    "name": ["Well Name", "Well_Name", "WellName", "Name", "Lease Name"],
    "type": ["Well Type", "Well_Type", "WellType", "Type"],
    "status": ["Well Status", "Well_Status", "WellStatus", "Status"],
    "state": ["State", "State Name", "State_Name", "STATE_ABBR", "ST"],
    "county": ["County", "County Name", "County_Name", "COUNTY_NAME"],
    "lat": ["Latitude", "LAT", "Lat_Dec", "LatitudeDD", "Y", "__lat"],
    "lon": ["Longitude", "LONG", "LON", "Lon_Dec", "LongitudeDD", "X", "__lon"],
    "surface_owner": ["Surface Ownership", "Surface_Owner", "Surface Owner", "Land Ownership", "Surface"],
    "mineral_owner": ["Subsurface Ownership", "Mineral Ownership", "Mineral_Owner", "Subsurface"],
}

REQUIRED = ("state", "lat", "lon")


@dataclass
class OrphanWell:
    idx: int
    state: str
    lon: float
    lat: float
    api: str | None
    raw_id: str
    name: str = ""
    type: str = ""
    status: str = ""
    county: str = ""
    surface_owner: str = ""
    mineral_owner: str = ""
    # populated by join
    extra: dict = field(default_factory=dict)


def detect_columns(headers, overrides: dict | None = None) -> dict[str, str | None]:
    cols = {k: find_column(headers, v) for k, v in CANDIDATES.items()}
    for k, v in (overrides or {}).items():
        cols[k] = v
    missing = [k for k in REQUIRED if not cols.get(k)]
    if missing:
        raise SystemExit(
            f"USGS file: could not find columns for {missing}. Headers: {list(headers)}. "
            "Pass --usgs-columns to map them."
        )
    return cols


def load(path: Path, overrides: dict | None = None) -> tuple[list[OrphanWell], dict]:
    rows = read_table(path)
    wells: list[OrphanWell] = []
    stats = {"rows": 0, "bad_location": 0, "bad_state": 0, "no_api": 0}
    cols = None
    for row in rows:
        if cols is None:
            cols = detect_columns(row.keys(), overrides)
        stats["rows"] += 1

        def g(k):
            c = cols.get(k)
            return (row.get(c) or "").strip() if c else ""

        st = state_code(g("state"))
        if not st:
            stats["bad_state"] += 1
            continue
        lon, lat = parse_float(g("lon")), parse_float(g("lat"))
        if lon is not None and lon > 0 and lat is not None and valid_lonlat(-lon, lat):
            lon = -lon  # western-hemisphere longitudes recorded without sign
        if not valid_lonlat(lon, lat):
            stats["bad_location"] += 1
            continue
        raw_id = g("api") or g("well_id")
        api = normalize_api(g("api"), st) if cols.get("api") else None
        if api is None:
            stats["no_api"] += 1
        wells.append(OrphanWell(
            idx=len(wells), state=st, lon=lon, lat=lat, api=api, raw_id=raw_id,
            name=g("name"), type=g("type"), status=g("status"), county=g("county"),
            surface_owner=g("surface_owner"), mineral_owner=g("mineral_owner"),
        ))
    stats["columns"] = cols or {}
    stats["loaded"] = len(wells)
    return wells, stats
