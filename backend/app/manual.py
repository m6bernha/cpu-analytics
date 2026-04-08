"""Manual meet entry: produce a lifter-history shape from user-supplied rows.

Used by the Lifter Lookup tab when a lifter isn't in OpenIPF (e.g. local-only
meets) or when the user wants to project hypothetical totals against cohort
norms. Output shape matches lifters.get_lifter_history so the frontend can
render manual and real lifters with the same component.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class ManualMeetEntry(BaseModel):
    date: date
    total_kg: float = Field(gt=0)
    bodyweight_kg: float | None = None
    weight_class: str | None = None  # canonical form, e.g. "83" or "120+"
    squat_kg: float | None = None
    bench_kg: float | None = None
    deadlift_kg: float | None = None
    meet_name: str | None = None


class ManualTrajectoryRequest(BaseModel):
    name: str = "(manual entry)"
    sex: str  # "M" or "F"
    equipment: str = "Raw"
    event: str = "SBD"
    entries: list[ManualMeetEntry]


def build_manual_trajectory(req: ManualTrajectoryRequest) -> dict[str, Any]:
    if not req.entries:
        return {
            "name": req.name,
            "found": True,
            "sex": req.sex,
            "federation": "(manual)",
            "country": None,
            "latest_equipment": req.equipment,
            "latest_weight_class": None,
            "meet_count": 0,
            "best_total_kg": 0.0,
            "meets": [],
        }

    sorted_entries = sorted(req.entries, key=lambda e: e.date)
    first_total = sorted_entries[0].total_kg
    first_date = sorted_entries[0].date

    meets: list[dict[str, Any]] = []
    for e in sorted_entries:
        meets.append(
            {
                "Name": req.name,
                "Sex": req.sex,
                "Federation": "(manual)",
                "Country": None,
                "Equipment": req.equipment,
                "Tested": None,
                "Event": req.event,
                "Division": "Open",
                "Age": None,
                "CanonicalWeightClass": e.weight_class,
                "Date": e.date.isoformat(),
                "TotalKg": e.total_kg,
                "Best3SquatKg": e.squat_kg,
                "Best3BenchKg": e.bench_kg,
                "Best3DeadliftKg": e.deadlift_kg,
                "Dots": None,
                "MeetName": e.meet_name,
                "MeetCountry": None,
                "TotalDiffFromFirst": e.total_kg - first_total,
                "DaysFromFirst": (e.date - first_date).days,
            }
        )

    return {
        "name": req.name,
        "found": True,
        "sex": req.sex,
        "federation": "(manual)",
        "country": None,
        "latest_equipment": req.equipment,
        "latest_weight_class": meets[-1]["CanonicalWeightClass"],
        "meet_count": len(meets),
        "best_total_kg": max(m["TotalKg"] for m in meets),
        "meets": meets,
    }
