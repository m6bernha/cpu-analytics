"""Enumerated filter values for the frontend filter panel."""

from __future__ import annotations

from typing import Any

from .data import get_conn


AGE_CATEGORIES = ["All", "Sub-Jr", "Jr", "Open", "M1", "M2", "M3", "M4"]
X_AXIS_OPTIONS = ["Meet #", "Days", "Weeks", "Months", "Years"]

MEN_CLASSES = ["53", "59", "66", "74", "83", "93", "105", "120", "120+"]
WOMEN_CLASSES = ["47", "52", "57", "63", "69", "76", "84", "84+"]


def get_filters() -> dict[str, Any]:
    conn = get_conn()

    def distinct(col: str) -> list[str]:
        rows = conn.execute(
            f"SELECT DISTINCT {col} FROM openipf WHERE {col} IS NOT NULL ORDER BY {col}"
        ).fetchall()
        return [r[0] for r in rows]

    # Division values from the dataset, with "All" prepended.
    division_rows = conn.execute(
        "SELECT DISTINCT Division FROM openipf "
        "WHERE Division IS NOT NULL AND Division != '' "
        "ORDER BY Division"
    ).fetchall()
    divisions = ["All"] + [r[0] for r in division_rows]

    return {
        "sex": distinct("Sex"),
        "equipment": distinct("Equipment"),
        "tested": distinct("Tested"),
        "event": distinct("Event"),
        "federation": distinct("Federation"),
        "country": distinct("Country"),
        "division": divisions,
        "weight_class": {
            "M": MEN_CLASSES,
            "F": WOMEN_CLASSES,
        },
        "age_category": AGE_CATEGORIES,
        "x_axis": X_AXIS_OPTIONS,
    }
