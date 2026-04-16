"""Lifter search and single-lifter history.

Search by name with optional federation/country/sex/equipment filters. Returns
matching lifters with light metadata. History returns one row per meet for the
selected lifter, with TotalDiffFromFirst computed in SQL.
"""

from __future__ import annotations

from typing import Any

from .data import get_conn
from .scope import DEFAULT_COUNTRY, DEFAULT_PARENT_FEDERATION


def search_lifters(
    q: str,
    sex: str | None = None,
    federation: str | None = None,
    country: str | None = DEFAULT_COUNTRY,
    parent_federation: str | None = DEFAULT_PARENT_FEDERATION,
    equipment: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Case-insensitive substring match on Name with optional filters.

    Returns one row per distinct lifter, with the most recent meet's metadata
    so the caller can disambiguate common names.
    """
    if not q or len(q.strip()) < 2:
        return []

    clauses: list[str] = ["LOWER(Name) LIKE ?"]
    params: list[Any] = [f"%{q.lower().strip()}%"]

    def eq(col: str, val: str | None) -> None:
        if val:
            clauses.append(f"{col} = ?")
            params.append(val)

    eq("Sex", sex)
    eq("Federation", federation)
    eq("Country", country)
    eq("ParentFederation", parent_federation)
    eq("Equipment", equipment)

    where_sql = " AND ".join(clauses)
    sql = f"""
        WITH matches AS (
            SELECT
                Name,
                Sex,
                Federation,
                Country,
                Equipment,
                CanonicalWeightClass,
                Date,
                TotalKg,
                ROW_NUMBER() OVER (PARTITION BY Name ORDER BY Date DESC, TotalKg DESC, MeetName DESC) AS rn,
                COUNT(*) OVER (PARTITION BY Name) AS meet_count,
                MAX(TotalKg) OVER (PARTITION BY Name) AS best_total
            FROM openipf
            WHERE {where_sql}
        )
        SELECT
            Name,
            Sex,
            Federation,
            Country,
            Equipment AS LatestEquipment,
            CanonicalWeightClass AS LatestWeightClass,
            Date AS LatestMeetDate,
            best_total AS BestTotalKg,
            meet_count AS MeetCount
        FROM matches
        WHERE rn = 1
        ORDER BY best_total DESC
        LIMIT ?
    """
    params.append(limit)
    rows = get_conn().execute(sql, params).df().to_dict(orient="records")

    for r in rows:
        if r.get("LatestMeetDate") is not None:
            r["LatestMeetDate"] = str(r["LatestMeetDate"])[:10]
    return rows


def get_lifter_history(name: str) -> dict[str, Any]:
    """Return all meets for a single lifter, with computed TotalDiffFromFirst.

    Match is exact (case-sensitive) because the search endpoint already
    canonicalized to a real Name string.
    """
    sql = """
        WITH lifter AS (
            SELECT
                Name, Sex, Federation, Country, Equipment, Tested, Event, Division,
                Age, CanonicalWeightClass, Date, TotalKg,
                Best3SquatKg, Best3BenchKg, Best3DeadliftKg, Dots,
                MeetName, MeetCountry,
                FIRST_VALUE(TotalKg) OVER (PARTITION BY Name ORDER BY Date, TotalKg DESC, MeetName) AS FirstTotal,
                MIN(Date) OVER (PARTITION BY Name) AS FirstDate
            FROM openipf
            WHERE Name = ?
        )
        SELECT
            Name, Sex, Federation, Country, Equipment, Tested, Event, Division,
            Age, CanonicalWeightClass, Date, TotalKg,
            Best3SquatKg, Best3BenchKg, Best3DeadliftKg, Dots,
            MeetName, MeetCountry,
            (TotalKg - FirstTotal) AS TotalDiffFromFirst,
            DATEDIFF('day', FirstDate, Date) AS DaysFromFirst
        FROM lifter
        ORDER BY Date
    """
    df = get_conn().execute(sql, [name]).df()
    if df.empty:
        return {"name": name, "meets": [], "found": False}

    meets = df.to_dict(orient="records")

    # PR detection: a meet is a PR if its TotalKg is strictly greater than
    # all previous meets of the same Event type. This avoids comparing a
    # bench-only total against an SBD total.
    best_by_event: dict[str, float] = {}
    for m in meets:
        if m.get("Date") is not None:
            m["Date"] = str(m["Date"])[:10]
        ev = m.get("Event", "")
        total = m.get("TotalKg")
        if total is not None:
            prev_best = best_by_event.get(ev)
            m["is_pr"] = prev_best is None or total > prev_best
            best_by_event[ev] = max(total, prev_best or 0)
        else:
            m["is_pr"] = False

    first = meets[0]

    # Weight class change detection: flag each meet where the class differs
    # from the previous meet and build a summary of transitions.
    prev_class = None
    weight_class_changes: list[dict[str, Any]] = []
    for m in meets:
        wc = m.get("CanonicalWeightClass")
        if prev_class is not None and wc is not None and wc != prev_class:
            m["class_changed"] = True
            weight_class_changes.append({
                "date": m["Date"],
                "from_class": prev_class,
                "to_class": wc,
            })
        else:
            m["class_changed"] = False
        if wc is not None:
            prev_class = wc

    # Rate of improvement: linear regression slope across ALL SBD meets.
    # This is more honest than first-to-last for non-monotonic careers
    # (e.g., a lifter who peaked then declined).
    import numpy as _np
    sbd = [m for m in meets if m.get("Event") == "SBD" and m.get("TotalKg") is not None]
    rate_kg_per_month = None
    if len(sbd) >= 2:
        days = _np.array([m["DaysFromFirst"] for m in sbd], dtype=float)
        totals = _np.array([m["TotalKg"] for m in sbd], dtype=float)
        if days[-1] > days[0]:  # at least some time span
            slope_per_day = float(_np.polyfit(days, totals, 1)[0])
            rate_kg_per_month = round(slope_per_day * 30.44, 2)

    return {
        "name": name,
        "found": True,
        "sex": first["Sex"],
        "federation": first["Federation"],
        "country": first["Country"],
        "latest_equipment": meets[-1]["Equipment"],
        "latest_weight_class": meets[-1]["CanonicalWeightClass"],
        "meet_count": len(meets),
        "best_total_kg": float(max(m["TotalKg"] for m in meets if m.get("TotalKg") is not None)),
        "rate_kg_per_month": rate_kg_per_month,
        "weight_class_changes": weight_class_changes,
        "meets": meets,
    }
