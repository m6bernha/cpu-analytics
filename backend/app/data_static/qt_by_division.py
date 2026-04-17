"""Age-division QT thresholds.

Data source: powerlifting.ca/qualifying-standards.

v1 ships with an empty override map. Every division falls back to the Open
thresholds loaded from qt_standards.parquet. The UI surfaces a
"Open values shown, age-specific coming" banner when the user picks a
non-Open division.

To activate age-specific thresholds for a division:
- Transcribe the powerlifting.ca table into a DataFrame shaped like
  qt_standards.parquet (columns: Sex, Level, WeightClass,
  QT_pre2025, QT_2025, QT_2027).
- Replace None in QT_OVERRIDES with that DataFrame.
- has_age_specific_qt() will then return True for that division and
  compute_blocks can swap the override in for the Open defaults.
"""

from __future__ import annotations

import pandas as pd

DIVISIONS: list[str] = [
    "Sub-Junior",
    "Junior",
    "Open",
    "Master 1",
    "Master 2",
    "Master 3",
    "Master 4",
]

# None means "no override, fall back to Open". Replace with a DataFrame
# to activate age-specific thresholds for that division.
QT_OVERRIDES: dict[str, pd.DataFrame | None] = {
    "Sub-Junior": None,  # TODO(powerlifting.ca/qualifying-standards)
    "Junior": None,      # TODO(powerlifting.ca/qualifying-standards)
    "Open": None,        # Open IS the base table, no override needed.
    "Master 1": None,    # TODO(powerlifting.ca/qualifying-standards)
    "Master 2": None,    # TODO(powerlifting.ca/qualifying-standards)
    "Master 3": None,    # TODO(powerlifting.ca/qualifying-standards)
    "Master 4": None,    # TODO(powerlifting.ca/qualifying-standards)
}


def has_age_specific_qt(division: str) -> bool:
    """Return True iff this division has real non-Open thresholds populated."""
    return QT_OVERRIDES.get(division) is not None
