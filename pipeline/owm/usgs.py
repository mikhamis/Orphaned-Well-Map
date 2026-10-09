"""Load the USGS Documented Orphaned Well Database (DOWDB) 2026 release.

Release: U.S. Geological Survey, "United States Documented Orphaned Well
Database 2026", https://doi.org/10.5066/P13FHBYG (supersedes Grove & Merrill
2022, https://doi.org/10.5066/P91PJETI).

Column names below come first from the 2026 release's FGDC metadata
(US_orphaned_wells_2026.xml, entity ``US_Orphaned_Wells_2026``); older
spellings follow so the 2022 file also loads. Run
``python -m owm.build --inspect FILE`` to see what was detected, and pass
``--usgs-columns '{"api": "My Column"}'`` to override.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .util import API_STATE_CODES, find_column, normalize_api, parse_float, read_table, state_code, valid_lonlat

CANDIDATES = {
    "record_key": ["record_key"],
    "id_type": ["primary_identifier_type"],
    "secondary_id": ["secondary_identifier"],
    "well_number": ["well_number"],
    "source": ["source"],
    "data_date": ["data_file_date"],
    "surface_agency": ["surface_fed_agency"],
    "subsurface_rights": ["subsurface_fed_rights"],
    "api": ["primary_identifier", "API", "API Number", "API_Number", "API_NUM", "APINumber", "API_No", "API14", "API12", "API10", "UWI"],
    "well_id": ["Well ID", "Well_ID", "WellID", "ID Number", "Permit", "Permit Number", "Well Number"],
    "name": ["well_name", "Well Name", "Well_Name", "WellName", "Name", "Lease Name"],
    "type": ["type", "Well Type", "Well_Type", "WellType", "Type"],
    "status": ["status", "Well Status", "Well_Status", "WellStatus", "Status"],
    "state": ["State", "State Name", "State_Name", "STATE_ABBR", "ST"],
    "county": ["County", "County Name", "County_Name", "COUNTY_NAME"],
    "lat": ["Latitude", "LAT", "Lat_Dec", "LatitudeDD", "Y", "__lat"],
    "lon": ["Longitude", "LONG", "LON", "Lon_Dec", "LongitudeDD", "X", "__lon"],
    "surface_owner": ["surface_owner_fed_dept", "Surface Ownership", "Surface_Owner", "Surface Owner", "Land Ownership", "Surface"],
    "mineral_owner": ["subsurface_owner_fed", "Subsurface Ownership", "Mineral Ownership", "Mineral_Owner", "Subsurface"],
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
    source: str = ""
    data_date: str = ""
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


def usgs_api(primary: str, id_type: str, secondary: str, state: str, has_type: bool) -> str | None:
    """API number for a USGS row, or None.

    Rows typed as a state-specific ID (IGSID, KYPermit, ILRefNo...) are not
    API numbers. For untyped rows, either identifier is accepted only if it
    normalizes to an API whose state prefix matches the row's state, so a
    permit number that happens to have 10 digits isn't mistaken for an API.
    """
    prefix = API_STATE_CODES.get(state)
    t = id_type.strip().upper()
    if has_type and t and t != "API":
        candidates = [secondary]
    elif t == "API":
        api = normalize_api(primary, state)
        if api:
            return api
        candidates = [secondary]
    else:
        candidates = [primary, secondary]
    for c in candidates:
        api = normalize_api(c, state)
        if api and api[:2] == prefix:
            return api
    return None


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
        api = usgs_api(g("api"), g("id_type"), g("secondary_id"), st, has_type=bool(cols.get("id_type")))
        if api is None:
            stats["no_api"] += 1
        wells.append(OrphanWell(
            idx=len(wells), state=st, lon=lon, lat=lat, api=api, raw_id=raw_id,
            name=" ".join(x for x in (g("name"), g("well_number")) if x),
            type=g("type"), status=g("status"), county=g("county"),
            surface_owner=" / ".join(x for x in (g("surface_owner"), g("surface_agency")) if x),
            mineral_owner=" / ".join(x for x in (g("mineral_owner"), g("subsurface_rights")) if x),
            source=g("source"), data_date=g("data_date"),
        ))
    stats["columns"] = cols or {}
    stats["loaded"] = len(wells)
    return wells, stats
