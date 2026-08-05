"""Meet result pages: every result recorded at one meet.

Phase 1c of the stateless social layer (docs/adr/0002-social-layer-stateless.md).

A meet is keyed by (MeetName, Date). Verified unique in the Canada+IPF
parquet: zero name+date pairs span more than one federation/country.

Two scope truths this module must not paper over:

* **Canadian lifters only.** The parquet is filtered to Country=Canada at
  preprocess (see `data/preprocess.py`), so a page for an international
  meet shows the CANADIAN contingent, not the whole meet. Responses carry
  `canadian_scope_only=True` so the UI can say that plainly rather than
  implying a complete result set.
* **Everything that happened, not just Raw SBD.** Unlike Rankings, a meet
  page is a record. Filtering out bench-only or equipped lifters would
  erase them from their own meet, so all events and equipment are
  included and grouped.
"""

from __future__ import annotations

import re
from typing import Any

from .data import get_cursor
from .scope import DEFAULT_COUNTRY, DEFAULT_PARENT_FEDERATION

# Display order for groups. Anything unlisted sorts after, alphabetically.
_EQUIPMENT_ORDER = ["Raw", "Wraps", "Single-ply", "Multi-ply", "Unlimited"]
_EVENT_ORDER = ["SBD", "B", "BD", "SB", "SD", "S", "D"]
_SEX_ORDER = ["F", "M"]

MAX_ROWS = 2000  # Largest real meet is ~850 rows; this is a sanity bound.


def _rank_in(value: Any, order: list[str]) -> tuple[int, str]:
    """Sort key: listed values in order, then unlisted alphabetically."""
    s = "" if value is None else str(value)
    return (order.index(s), "") if s in order else (len(order), s)


def _weight_class_key(wc: Any) -> tuple[float, int, str]:
    """Numeric ascending; a '+' class sorts just after its own number."""
    s = "" if wc is None else str(wc)
    m = re.match(r"^(\d+(?:\.\d+)?)(\+?)$", s)
    if not m:
        return (float("inf"), 0, s)   # unparseable classes last
    return (float(m.group(1)), 1 if m.group(2) else 0, s)


def _place_key(place: Any) -> tuple[int, float, str]:
    """Numeric placings ascending, then non-numeric (DQ/DD/NS/G) last."""
    s = "" if place is None else str(place).strip()
    try:
        return (0, float(s), "")
    except ValueError:
        return (1, 0.0, s)


def _division_key(division: Any) -> tuple[int, str]:
    """Open first, then other divisions alphabetically, unknown last.

    CPU awards placings PER DIVISION inside a weight class, so a single
    83 kg group legitimately contains eight lifters placed "1". Sorting
    on place alone renders that as a wall of 1s that reads like broken
    data; ordering by division first keeps each division's podium
    contiguous.
    """
    if division is None:
        return (2, "")
    s = str(division).strip()
    if not s:
        return (2, "")
    return (0, "") if s == "Open" else (1, s)


def get_meet_results(meet_name: str, date: str) -> dict[str, Any]:
    """All recorded results for one meet, grouped for display.

    Groups are sex -> equipment -> event -> weight class; results inside a
    group are ordered by placing. Returns a shape-complete empty response
    when the meet is unknown so the frontend types always hold.
    """
    empty = {
        "found": False,
        "meet_name": meet_name,
        "date": date,
        "federation": None,
        "meet_country": None,
        "n_results": 0,
        "n_lifters": 0,
        "groups": [],
        "canadian_scope_only": True,
    }
    if not meet_name or not re.match(r"^\d{4}-\d{2}-\d{2}$", date or ""):
        return empty

    sql = """
        SELECT
            Name, Sex, Equipment, Event, Division, CanonicalWeightClass,
            BodyweightKg, Best3SquatKg, Best3BenchKg, Best3DeadliftKg,
            TotalKg, Goodlift, Place, Age, Federation, MeetCountry
        FROM openipf
        WHERE MeetName = ? AND CAST(Date AS VARCHAR)[1:10] = ?
          AND Country = ? AND ParentFederation = ?
        LIMIT ?
    """
    rows = (
        get_cursor()
        .execute(
            sql,
            [meet_name, date, DEFAULT_COUNTRY, DEFAULT_PARENT_FEDERATION, MAX_ROWS],
        )
        .fetchall()
    )
    if not rows:
        return empty

    cols = [
        "name", "sex", "equipment", "event", "division", "weight_class",
        "bodyweight_kg", "squat_kg", "bench_kg", "deadlift_kg",
        "total_kg", "glp", "place", "age", "federation", "meet_country",
    ]
    records = [dict(zip(cols, r)) for r in rows]

    grouped: dict[tuple, list[dict[str, Any]]] = {}
    for rec in records:
        key = (rec["sex"], rec["equipment"], rec["event"], rec["weight_class"])
        grouped.setdefault(key, []).append(rec)

    groups: list[dict[str, Any]] = []
    for (sex, equipment, event, weight_class), items in grouped.items():
        items.sort(key=lambda r: (_division_key(r["division"]), _place_key(r["place"])))
        groups.append({
            "sex": sex,
            "equipment": equipment,
            "event": event,
            "weight_class": weight_class,
            "n_results": len(items),
            "n_divisions": len({r["division"] for r in items}),
            "results": [
                {
                    "place": r["place"],
                    "name": r["name"],
                    "division": r["division"],
                    "bodyweight_kg": _f(r["bodyweight_kg"]),
                    "squat_kg": _f(r["squat_kg"]),
                    "bench_kg": _f(r["bench_kg"]),
                    "deadlift_kg": _f(r["deadlift_kg"]),
                    "total_kg": _f(r["total_kg"]),
                    "glp": round(r["glp"], 2) if r["glp"] is not None else None,
                }
                for r in items
            ],
        })

    groups.sort(
        key=lambda g: (
            _rank_in(g["sex"], _SEX_ORDER),
            _rank_in(g["equipment"], _EQUIPMENT_ORDER),
            _rank_in(g["event"], _EVENT_ORDER),
            _weight_class_key(g["weight_class"]),
        )
    )

    return {
        "found": True,
        "meet_name": meet_name,
        "date": date,
        "federation": records[0]["federation"],
        "meet_country": records[0]["meet_country"],
        "n_results": len(records),
        "n_lifters": len({r["name"] for r in records}),
        "groups": groups,
        # See the module docstring: the parquet is Canada-scoped, so an
        # international meet shows only the Canadian contingent.
        "canadian_scope_only": True,
    }


def _f(v: Any) -> float | None:
    return float(v) if v is not None else None
