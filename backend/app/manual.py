"""Manual meet entry: produce a lifter-history shape from user-supplied rows.

Used by the Lifter Lookup tab when a lifter isn't in OpenIPF (e.g. local-only
meets) or when the user wants to project hypothetical totals against cohort
norms. Output shape matches lifters.get_lifter_history so the frontend can
render manual and real lifters with the same component.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# Upper bound on kg values. A current world record total is ~1100 kg.
# Rejecting values above 2000 kg catches typos and DoS-shaped inputs
# without excluding any plausible real total.
MAX_KG = 2000.0

# Tolerance when checking user-supplied total against S+B+D. Kept tight
# because CPU/IPF totals are exact sums of attempts in 2.5 kg increments;
# a mismatch larger than this points to a typo worth surfacing.
TOTAL_LIFTS_TOLERANCE_KG = 0.01


class ManualMeetEntry(BaseModel):
    date: date
    total_kg: float | None = Field(default=None, gt=0, le=MAX_KG)
    bodyweight_kg: float | None = Field(default=None, ge=30, le=300)
    weight_class: str | None = Field(default=None, max_length=10)
    squat_kg: float | None = Field(default=None, gt=0, le=MAX_KG)
    bench_kg: float | None = Field(default=None, gt=0, le=MAX_KG)
    deadlift_kg: float | None = Field(default=None, gt=0, le=MAX_KG)
    meet_name: str | None = Field(default=None, max_length=200)

    @field_validator("date")
    @classmethod
    def date_within_reasonable_range(cls, v: date) -> date:
        if v.year < 1960 or v.year > date.today().year + 1:
            raise ValueError(f"Date {v} is outside the supported range (1960-next year)")
        return v

    @model_validator(mode="after")
    def _reconcile_total_and_lifts(self) -> "ManualMeetEntry":
        lifts = (self.squat_kg, self.bench_kg, self.deadlift_kg)
        has_all_lifts = all(v is not None for v in lifts)
        has_any_lift = any(v is not None for v in lifts)

        if has_any_lift and not has_all_lifts:
            raise ValueError(
                "Per-lift entries need squat, bench, and deadlift together. "
                "Leave all three blank to enter a total only."
            )

        if self.total_kg is None:
            if not has_all_lifts:
                raise ValueError(
                    "Each meet needs either a total or all three lifts."
                )
            computed = self.squat_kg + self.bench_kg + self.deadlift_kg
            if computed > MAX_KG:
                raise ValueError(
                    f"Sum of lifts {computed:.1f} kg exceeds the {MAX_KG:.0f} kg cap."
                )
            self.total_kg = round(computed, 2)
            return self

        if has_all_lifts:
            computed = self.squat_kg + self.bench_kg + self.deadlift_kg
            if abs(computed - self.total_kg) > TOTAL_LIFTS_TOLERANCE_KG:
                raise ValueError(
                    f"Total {self.total_kg:.1f} kg does not match sum of lifts "
                    f"{computed:.1f} kg "
                    f"(squat {self.squat_kg} + bench {self.bench_kg} + "
                    f"deadlift {self.deadlift_kg})."
                )
        return self


class ManualTrajectoryRequest(BaseModel):
    name: str = Field(default="(manual entry)", max_length=100)
    sex: str = Field(pattern=r"^[MF]$")
    equipment: str = Field(default="Raw", max_length=20)
    event: str = Field(default="SBD", max_length=5)
    entries: list[ManualMeetEntry] = Field(max_length=200)


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
            "rate_kg_per_month": None,
            "weight_class_changes": [],
            "projection": None,
            "percentile_rank": None,
            "meets": [],
        }

    sorted_entries = sorted(req.entries, key=lambda e: e.date)
    first_total = sorted_entries[0].total_kg
    first_date = sorted_entries[0].date

    meets: list[dict[str, Any]] = []
    prev_class: str | None = None
    weight_class_changes: list[dict[str, Any]] = []
    is_sbd = req.event == "SBD"
    prev_best_total: float | None = None
    for e in sorted_entries:
        class_changed = prev_class is not None and e.weight_class is not None and e.weight_class != prev_class
        if class_changed:
            weight_class_changes.append({
                "date": e.date.isoformat(),
                "from_class": prev_class,
                "to_class": e.weight_class,
            })
        is_pr = is_sbd and (prev_best_total is None or e.total_kg > prev_best_total)
        if prev_best_total is None or e.total_kg > prev_best_total:
            prev_best_total = e.total_kg
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
                "Goodlift": None,
                "MeetName": e.meet_name,
                "MeetCountry": None,
                "TotalDiffFromFirst": e.total_kg - first_total,
                "DaysFromFirst": (e.date - first_date).days,
                "is_pr": is_pr,
                "class_changed": class_changed,
            }
        )
        if e.weight_class is not None:
            prev_class = e.weight_class

    # Rate of improvement: regression slope if we have enough SBD points
    rate_kg_per_month: float | None = None
    if is_sbd and len(meets) >= 2:
        import numpy as _np
        days = _np.array([m["DaysFromFirst"] for m in meets], dtype=float)
        totals = _np.array([m["TotalKg"] for m in meets], dtype=float)
        if days[-1] > days[0]:
            slope_per_day = float(_np.polyfit(days, totals, 1)[0])
            rate_kg_per_month = round(slope_per_day * 30.44, 2)

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
        "rate_kg_per_month": rate_kg_per_month,
        "weight_class_changes": weight_class_changes,
        "projection": None,  # Manual entries don't get projection (no cohort context)
        "percentile_rank": None,  # Can't compute without a dataset cohort
        "meets": meets,
    }
