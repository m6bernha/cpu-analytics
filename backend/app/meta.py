"""Data freshness metadata for the frontend header badge.

The openipf parquet only changes on the weekly data refresh, which
restarts the container, so a container-lifetime lru_cache is safe here
(same convention as filters.get_filters).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .data import with_cursor


@lru_cache(maxsize=1)
def get_freshness() -> dict[str, Any]:
    """Latest meet date + row count from the openipf view."""
    with with_cursor() as cur:
        row = cur.execute(
            # Date may be DATE or TIMESTAMP depending on parquet vintage;
            # double cast normalizes to 'YYYY-MM-DD'.
            "SELECT CAST(CAST(MAX(Date) AS DATE) AS VARCHAR) AS latest, "
            "COUNT(*) AS n FROM openipf"
        ).fetchone()
    latest, n_rows = row if row is not None else (None, 0)
    return {
        "latest_meet_date": latest,
        "row_count": int(n_rows or 0),
    }
