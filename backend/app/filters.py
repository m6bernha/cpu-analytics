"""Enumerated filter values for the frontend filter panel.

Most values are hardcoded to the CPU-canonical taxonomy so the UI shows
friendly labels (Raw/Equipped, Full Power/Bench Only, CPU age divisions)
regardless of what free-text appears in OpenIPF's raw export. The backend
filter-clause builder in progression.py knows how to translate these
canonical labels back into the underlying OpenIPF values via alias tables.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any


X_AXIS_OPTIONS = ["Meet #", "Days", "Weeks", "Months", "Years", "Career quartile"]

MEN_CLASSES = ["59", "66", "74", "83", "93", "105", "120", "120+"]
WOMEN_CLASSES = ["47", "52", "57", "63", "69", "76", "84", "84+"]

# Equipment: CPU bifurcates into Classic Raw and Equipped. OpenIPF stores
# Single-ply / Wraps / Multi-ply separately; the backend collapses them
# into "Equipped" when that UI value is selected.
EQUIPMENT = ["All", "Raw", "Equipped"]

# Event: CPU only runs two event types: Full Power (SBD) and Bench Only (B).
# The other OpenIPF codes (BD, SD, SB, S, D) are non-CPU-standard combos
# that we don't surface. Individual-lift analysis (squat, bench, or
# deadlift trajectory from SBD meets) is available via the per-lift
# toggle in the Progression tab, which uses a separate endpoint.
EVENT = ["SBD", "B"]

# CPU canonical age divisions. These are the user-facing labels; the
# backend filter-clause builder maps them to alias lists matching free-text
# Division strings that actually appear in OpenIPF's CPU meet data.
CPU_DIVISIONS = [
    "All",
    "Youth 1",
    "Youth 2",
    "Youth 3",
    "Sub-Junior",
    "Junior",
    "Open",
    "Master 1",
    "Master 2",
    "Master 3",
    "Master 4",
]


@lru_cache(maxsize=1)
def get_filters() -> dict[str, Any]:
    return {
        "sex": ["F", "M"],
        "equipment": EQUIPMENT,
        "tested": ["Yes"],  # CPU/IPF is drug-tested by default
        "event": EVENT,
        "division": CPU_DIVISIONS,
        "weight_class": {
            "M": MEN_CLASSES,
            "F": WOMEN_CLASSES,
        },
        "x_axis": X_AXIS_OPTIONS,
    }
