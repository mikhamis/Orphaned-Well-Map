"""Shared helpers: column detection, API-number normalization, spatial index."""
from __future__ import annotations

import csv
import gzip
import json
import math
import re
from pathlib import Path
from typing import Iterable, Iterator

# API state codes (API Bulletin D12A). These are NOT FIPS codes.
API_STATE_CODES = {
    "AL": "01", "AZ": "02", "AR": "03", "CA": "04", "CO": "05", "CT": "06",
    "DE": "07", "DC": "08", "FL": "09", "GA": "10", "ID": "11", "IL": "12",
    "IN": "13", "IA": "14", "KS": "15", "KY": "16", "LA": "17", "ME": "18",
    "MD": "19", "MA": "20", "MI": "21", "MN": "22", "MS": "23", "MO": "24",
    "MT": "25", "NE": "26", "NV": "27", "NH": "28", "NJ": "29", "NM": "30",
    "NY": "31", "NC": "32", "ND": "33", "OH": "34", "OK": "35", "OR": "36",
    "PA": "37", "RI": "38", "SC": "39", "SD": "40", "TN": "41", "TX": "42",
    "UT": "43", "VT": "44", "VA": "45", "WA": "46", "WV": "47", "WI": "48",
    "WY": "49", "AK": "50", "HI": "51",
}

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}
_NAME_TO_CODE = {v.lower(): k for k, v in STATE_NAMES.items()}

# Operator values that mean "no real operator on record". Matched after
# normalize_name(), as whole strings or as prefixes.
PLACEHOLDER_OPERATORS = (
    "unknown", "unk", "orphan", "orphaned", "orphan well", "orphan well program",
    "abandoned", "none", "na", "n a", "no operator", "operator unknown",
    "state of", "plugging fund", "abandoned well program",
    "otc occ not assigned",  # Oklahoma RBDMS: no operator of record
    "state fund plugging",   # Oklahoma RBDMS: state plugging program
)


def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def find_column(headers: Iterable[str], candidates: Iterable[str]) -> str | None:
    """Return the header whose normalized form matches the first candidate found."""
    by_norm = {norm_key(h): h for h in headers}
    for c in candidates:
        hit = by_norm.get(norm_key(c))
        if hit is not None:
            return hit
    return None


def state_code(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip()
    if v.upper() in STATE_NAMES:
        return v.upper()
    return _NAME_TO_CODE.get(v.lower())


def normalize_api(raw: str | None, state: str | None = None) -> str | None:
    """Reduce an API well number to its 10-digit form (state+county+unique).

    Handles dashes/spaces, 12/14-digit forms (sidetrack and event suffixes are
    dropped) and a leading zero lost to spreadsheet software (states 01-09).
    If ``state`` is given and the number lacks a state prefix (8 digits:
    county+unique, used by some state agencies), the prefix is added.
    Returns None when the value doesn't look like an API number.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if re.fullmatch(r"\d+\.0+", s):  # 4212345678.0 from float-typed columns
        s = s.split(".")[0]
    digits = re.sub(r"\D", "", s)
    if len(digits) in (9, 11, 13):
        digits = "0" + digits
    if len(digits) == 8 and state in API_STATE_CODES:
        digits = API_STATE_CODES[state] + digits
    if len(digits) not in (10, 12, 14):
        return None
    api10 = digits[:10]
    if set(api10[2:]) == {"0"}:
        return None
    return api10


def normalize_id(raw: str | None) -> str | None:
    """State-specific well IDs (permit numbers etc.): digits/letters, no leading zeros."""
    if raw is None:
        return None
    s = re.sub(r"[^0-9A-Za-z]", "", str(raw)).upper().lstrip("0")
    return s or None


def normalize_name(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"[^a-z0-9& ]", " ", str(s).lower())
    return re.sub(r"\s+", " ", s).strip()


def is_placeholder_operator(name: str | None) -> bool:
    n = normalize_name(name)
    if not n:
        return True
    return any(n == p or n.startswith(p + " ") for p in PLACEHOLDER_OPERATORS)


def parse_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(str(v).strip())
    except ValueError:
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def valid_lonlat(lon: float | None, lat: float | None) -> bool:
    """Loose bounds for the US incl. Alaska; rejects 0,0 and swapped coords."""
    if lon is None or lat is None:
        return False
    return -180 <= lon <= -60 and 17 <= lat <= 72


EARTH_R = 6_371_008.8


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


class GridIndex:
    """Uniform lon/lat grid for radius queries. Cell size is in degrees."""

    def __init__(self, cell_deg: float = 0.02):
        self.cell = cell_deg
        self.cells: dict[tuple[int, int], list[int]] = {}
        self.lon: list[float] = []
        self.lat: list[float] = []

    def add(self, lon: float, lat: float) -> int:
        i = len(self.lon)
        self.lon.append(lon)
        self.lat.append(lat)
        key = (int(math.floor(lon / self.cell)), int(math.floor(lat / self.cell)))
        self.cells.setdefault(key, []).append(i)
        return i

    def within(self, lon: float, lat: float, radius_m: float) -> list[tuple[float, int]]:
        """(distance_m, item) pairs within radius, nearest first."""
        dlat = math.degrees(radius_m / EARTH_R)
        coslat = max(math.cos(math.radians(lat)), 1e-6)
        dlon = dlat / coslat
        x0, x1 = int(math.floor((lon - dlon) / self.cell)), int(math.floor((lon + dlon) / self.cell))
        y0, y1 = int(math.floor((lat - dlat) / self.cell)), int(math.floor((lat + dlat) / self.cell))
        out = []
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for i in self.cells.get((x, y), ()):
                    d = haversine_m(lon, lat, self.lon[i], self.lat[i])
                    if d <= radius_m:
                        out.append((d, i))
        out.sort()
        return out


def read_table(path: Path, encoding: str = "utf-8-sig", delimiter: str | None = None) -> Iterator[dict]:
    """Yield rows from CSV/TSV/TXT or GeoJSON (optionally .gz) as dicts.

    GeoJSON point features get synthetic ``__lon``/``__lat`` keys. Other
    formats (shapefile, file geodatabase, xlsx) should be converted first,
    e.g. ``ogr2ogr -f CSV out.csv in.gdb -lco GEOMETRY=AS_XY``.
    """
    path = Path(path)
    gz = path.suffix.lower() == ".gz"
    suffix = (path.with_suffix("") if gz else path).suffix.lower()

    def opener(**kw):
        return gzip.open(path, "rt", **kw) if gz else path.open(**kw)

    if suffix in (".geojson", ".json"):
        with opener(encoding=encoding) as f:
            data = json.load(f)
        for feat in data.get("features", []):
            props = dict(feat.get("properties") or {})
            geom = feat.get("geometry") or {}
            if geom.get("type") == "Point":
                props["__lon"], props["__lat"] = geom["coordinates"][:2]
            yield props
        return
    with opener(encoding=encoding, errors="replace", newline="") as f:
        sample = f.read(65536)
        f.seek(0)
        if delimiter is None:
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",\t|;").delimiter
            except csv.Error:
                delimiter = ","
        yield from csv.DictReader(f, delimiter=delimiter)


def write_json(path: Path, obj, compact: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
        else:
            json.dump(obj, f, indent=2, ensure_ascii=False)
