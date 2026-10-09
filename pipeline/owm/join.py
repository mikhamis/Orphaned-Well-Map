"""Join USGS orphaned wells to state records.

1. API match: USGS API (10-digit) == state record API (10-digit).
2. Location fallback: nearest state record within ``loc_tolerance_m`` when
   the USGS row has no usable API or the API isn't in the state file. These
   matches are weaker and are labelled as such in the output.
3. Nearby activity: active state wells within ``radius_m`` of the orphan.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .states import StateWell, latest_by_api
from .usgs import OrphanWell
from .util import GridIndex, is_placeholder_operator


@dataclass
class JoinParams:
    radius_m: float = 1609.344  # 1 mile
    loc_tolerance_m: float = 30.0
    nearest_n: int = 5


def join_state(orphans: list[OrphanWell], records: list[StateWell], p: JoinParams) -> dict:
    by_api = latest_by_api(records)

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
    for w in orphans:
        rec, method, dist = None, None, None
        if w.api and w.api in by_api:
            rec, method = by_api[w.api], "api"
        else:
            hits = loc_idx.within(w.lon, w.lat, p.loc_tolerance_m)
            if hits:
                dist, i = hits[0]
                rec, method = loc_recs[i], "location"
        e = w.extra
        e["match"] = method
        if rec is not None:
            stats["matched_" + method] += 1
            e["match_dist_m"] = round(dist, 1) if dist is not None else None
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
    stats["state_records"] = len(records)
    stats["state_records_active"] = len(act_recs)
    return dict(stats)
