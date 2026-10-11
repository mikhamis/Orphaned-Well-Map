"""Join USGS orphaned wells to state records.

1. API match: USGS API (10-digit) == state record API (10-digit).
1b. ID match: for states whose USGS rows carry a state-specific ID (e.g.
   Kentucky permit numbers), USGS primary_identifier == the config's
   ``columns.id``, both stripped of punctuation and leading zeros.
2. Location fallback: nearest state record within ``loc_tolerance_m`` when
   the USGS row has no usable API or the API isn't in the state file. These
   matches are weaker and are labelled as such in the output.
3. Nearby activity: active state wells within ``radius_m`` of the orphan.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .states import StateWell, latest_by_api
from .usgs import OrphanWell
from .util import GridIndex, haversine_m, is_placeholder_operator, normalize_id


@dataclass
class JoinParams:
    radius_m: float = 1609.344  # 1 mile
    loc_tolerance_m: float = 30.0
    nearest_n: int = 5
    disagree_m: float = 1000.0  # USGS vs state coordinates; flagged on the site


def _name_tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]{3,}", (s or "").lower())} - {"well", "unit", "the", "and", "lease", "est", "etal"}


def join_state(orphans: list[OrphanWell], records: list[StateWell], p: JoinParams,
               loc_cfg: dict | None = None) -> dict:
    """loc_cfg (state config "location_match"): {"tolerance_m": 300, "name_match": true, "usgs_id": "secondary"}
    widens the location fallback but then requires the USGS well name to share a word
    with the state record's lease or well name."""
    loc_tol = (loc_cfg or {}).get("tolerance_m", p.loc_tolerance_m)
    # "usgs_id": "secondary" joins columns.id to the USGS secondary_identifier
    # (value after any "Label:" prefix) instead of primary_identifier.
    use_secondary = (loc_cfg or {}).get("usgs_id") == "secondary"
    name_match = bool((loc_cfg or {}).get("name_match"))
    by_api = latest_by_api(records)
    by_id = latest_by_api(records, key="alt_id")

    loc_idx = GridIndex(0.01)
    loc_recs: list[StateWell] = []
    act_idx = GridIndex(0.02)
    act_recs: list[StateWell] = []
    for r in records:
        if not r.has_location:
            continue
        loc_idx.add(r.lon, r.lat)
        loc_recs.append(r)
        if r.active:
            act_idx.add(r.lon, r.lat)
            act_recs.append(r)

    stats = Counter()
    dists: list[float] = []
    for w in orphans:
        rec, method, dist = None, None, None
        wid = None
        if by_id:
            wid = normalize_id(w.secondary_id.split(":")[-1] if use_secondary else w.raw_id)
        if w.api and w.api in by_api:
            rec, method = by_api[w.api], "api"
        elif wid and wid in by_id:
            rec, method = by_id[wid], "id"
        else:
            hits = loc_idx.within(w.lon, w.lat, loc_tol)
            if name_match:
                wt = _name_tokens(w.name)
                hits = [(d, i) for d, i in hits
                        if wt & (_name_tokens(loc_recs[i].lease) | _name_tokens(loc_recs[i].well_name))]
            if hits:
                dist, i = hits[0]
                rec, method = loc_recs[i], "location"
        e = w.extra
        e["match"] = method
        if rec is not None:
            stats["matched_" + method] += 1
            if dist is None and rec.has_location:
                dist = haversine_m(w.lon, w.lat, rec.lon, rec.lat)
            e["match_dist_m"] = round(dist, 1) if dist is not None else None
            if dist is not None:
                dists.append(dist)
                stats["location_disagrees"] += dist > p.disagree_m
            e["state_api"] = rec.api
            e["operator"] = rec.operator
            e["operator_placeholder"] = is_placeholder_operator(rec.operator)
            e["state_status"] = rec.status
            e["lease"] = rec.lease
            if not e["operator_placeholder"]:
                stats["with_operator"] += 1
        else:
            stats["unmatched"] += 1

        exclude = {w.api, rec.api if rec else None} - {None}
        near = [(d, act_recs[i]) for d, i in act_idx.within(w.lon, w.lat, p.radius_m)]
        near = [(d, r) for d, r in near if r.api not in exclude and r is not rec]
        e["nearby_active"] = len(near)
        e["nearby"] = [
            [r.api or "", r.operator, r.lease, round(d)] for d, r in near[: p.nearest_n]
        ]
        ops = Counter(r.operator for _, r in near if not is_placeholder_operator(r.operator))
        e["nearby_operators"] = ops.most_common(5)
        if near:
            stats["with_nearby_active"] += 1
    if dists:
        dists.sort()
        stats["match_dist_median_m"] = round(dists[len(dists) // 2], 1)
        stats["match_dist_p95_m"] = round(dists[int(len(dists) * 0.95)], 1)
    stats["state_records"] = len(records)
    stats["state_records_active"] = len(act_recs)
    return dict(stats)
