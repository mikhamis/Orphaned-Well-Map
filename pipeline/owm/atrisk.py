"""Inactive or abandoned wells that still have an owner on record.

These are not orphans yet: the state still names a responsible operator. They
are the wells most likely to become orphans, so the site shows them as a
separate layer. Each state config defines what counts, under "at_risk":

    "at_risk": {"status": ["^Abandoned$"], "where": [{"column": "PLUG_DATE", "empty": true}],
                "require_operator": true, "definition": "..."}

Wells already in the USGS orphan set are excluded (by API number, state ID,
or a location within ``exclude_within_m`` of a USGS orphan).
"""
from __future__ import annotations

import re

from .states import StateWell, latest_by_api, where
from .usgs import OrphanWell
from .util import GridIndex, is_placeholder_operator


def select(cfg: dict, records: list[StateWell], orphans: list[OrphanWell],
           exclude_within_m: float = 30.0) -> list[StateWell]:
    rule = cfg.get("at_risk")
    if not rule:
        return []
    pats = [re.compile(p, re.I) for p in rule.get("status", [".*"])]
    rules = rule.get("where") or []
    taken_api = {w.api for w in orphans if w.api} | {w.extra.get("state_api") for w in orphans}
    grid = GridIndex(0.01)
    for w in orphans:
        grid.add(w.lon, w.lat)
    # one record per well, latest real operator first (same rule as the join)
    candidates = [r for r in records if any(p.search(r.status or "") for p in pats) and where(r.extra, rules)]
    if rule.get("require_operator"):
        candidates = [r for r in candidates if not is_placeholder_operator(r.operator)]
    by_api = latest_by_api(candidates)
    unique = list(by_api.values()) + [r for r in candidates if r.api is None]
    out = []
    for r in unique:
        if r.api and r.api in taken_api:
            continue
        if not r.has_location:
            continue
        if grid.within(r.lon, r.lat, exclude_within_m):
            continue
        out.append(r)
    return out


def summarize(selected: list[StateWell]) -> dict:
    named = [r for r in selected if not is_placeholder_operator(r.operator)]
    return {"count": len(selected), "with_operator": len(named)}
