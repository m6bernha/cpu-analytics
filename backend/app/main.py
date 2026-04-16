"""FastAPI app entry point.

Run locally:
    cd cpu-analytics
    uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

import math
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from . import filters as filters_mod
from . import lifters as lifters_mod
from . import progression as progression_mod
from . import qt as qt_mod
from .data import get_conn
from .manual import ManualTrajectoryRequest, build_manual_trajectory
from .scope import DEFAULT_COUNTRY, DEFAULT_PARENT_FEDERATION


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Pre-warm the DuckDB connection at container start.

    Without this, the first request after a cold boot pays the cost of
    downloading the parquet files (~28 MB) and registering the DuckDB
    views. Worse, the empty-equipment regression we saw on Vercel was
    consistent with a request landing partway through view registration.
    Pre-warming runs that work serially before the app accepts traffic.
    """
    try:
        conn = get_conn()
        # Touch each view so DuckDB actually opens the parquet, not just
        # records the parquet_scan SQL.
        n_meets = conn.execute("SELECT COUNT(*) FROM openipf").fetchone()[0]
        n_qt = conn.execute("SELECT COUNT(*) FROM qt_standards").fetchone()[0]
        print(f"[startup] warmed: openipf={n_meets:,} rows, qt_standards={n_qt} rows")
        # If either view is empty, the parquet is likely corrupt or truncated.
        # Delete the files so the next cold-start re-downloads, then log.
        if n_meets == 0 or n_qt == 0:
            import os
            from .data import OPENIPF_PARQUET, QT_PARQUET
            print(
                f"[startup] ERROR: parquet appears empty "
                f"(openipf={n_meets}, qt={n_qt}). Removing local files "
                f"so the next cold-start re-downloads."
            )
            for p in (OPENIPF_PARQUET, QT_PARQUET):
                try:
                    os.unlink(p)
                except OSError:
                    pass
    except Exception as exc:  # pragma: no cover — startup diagnostics
        # Log but continue: transient download failures will be retried
        # by get_conn() on the first real request. Only fatal-empty-parquet
        # above re-raises (and does so above this handler).
        print(f"[startup] warmup failed: {exc!r}")
    yield


app = FastAPI(
    title="CPU Powerlifting Analytics",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS:
#   - localhost dev origins always allowed
#   - any *.vercel.app preview/production URL allowed via regex
#   - extra origins (e.g. a custom domain) via the EXTRA_CORS_ORIGINS env var,
#     comma-separated
_extra = os.environ.get("EXTRA_CORS_ORIGINS", "")
_extra_origins = [o.strip() for o in _extra.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        *_extra_origins,
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _clean(obj: Any) -> Any:
    """Replace NaN/inf with None so JSON is valid."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/filters")
def api_filters() -> dict[str, Any]:
    return filters_mod.get_filters()


@app.get("/api/qt/standards")
def api_qt_standards() -> list[dict[str, Any]]:
    df = qt_mod.get_qt_standards()
    return _clean(df.to_dict(orient="records"))


@app.get("/api/qt/coverage")
def api_qt_coverage(
    country: str = Query("Canada"),
    federation: str = Query("CPU"),
    equipment: str = Query("Raw"),
    tested: str = Query("Yes"),
    event: str = Query("SBD"),
    age_filter: str = Query("open", description="'open' or 'all'"),
) -> list[dict[str, Any]]:
    df = qt_mod.compute_coverage(
        country=country,
        federation=federation,
        equipment=equipment,
        tested=tested,
        event=event,
        age_filter=age_filter,
    )
    return _clean(df.to_dict(orient="records"))


@app.get("/api/cohort/progression")
def api_progression(
    sex: str | None = Query(None),
    equipment: str | None = Query(None),
    tested: str | None = Query(None),
    event: str | None = Query(None),
    federation: str | None = Query(None),
    country: str | None = Query(DEFAULT_COUNTRY),
    parent_federation: str | None = Query(DEFAULT_PARENT_FEDERATION),
    weight_class: str | None = Query(None, description="Canonical class, e.g. '83' or '120+'. Use 'Overall' for no class filter."),
    division: str | None = Query(None, description="e.g. 'Open' to restrict to Open lifters."),
    age_category: str | None = Query(None, description="Sub-Jr/Jr/Open/M1/M2/M3/M4 or 'All'. Sparse Age column means many rows are silently dropped."),
    x_axis: str = Query("Days"),
    max_gap_months: int | None = Query(None, description="Exclude lifters with any inter-meet gap longer than this many months. Filters out comeback lifters."),
    same_class_only: bool = Query(False, description="Only include lifters who stayed in the same weight class for all meets in scope."),
) -> dict[str, Any]:
    return _clean(
        progression_mod.compute_progression(
            sex=sex,
            equipment=equipment,
            tested=tested,
            event=event,
            federation=federation,
            country=country,
            parent_federation=parent_federation,
            weight_class=weight_class,
            division=division,
            age_category=age_category,
            x_axis=x_axis,
            max_gap_months=max_gap_months,
            same_class_only=same_class_only,
        )
    )


@app.get("/api/cohort/lift_progression")
def api_lift_progression(
    sex: str | None = Query(None),
    equipment: str | None = Query(None),
    tested: str | None = Query(None),
    event: str | None = Query("SBD"),
    federation: str | None = Query(None),
    country: str | None = Query(DEFAULT_COUNTRY),
    parent_federation: str | None = Query(DEFAULT_PARENT_FEDERATION),
    weight_class: str | None = Query(None),
    division: str | None = Query(None),
    x_axis: str = Query("Years"),
) -> dict[str, Any]:
    """Per-lift (squat, bench, deadlift) cohort progression."""
    return _clean(
        progression_mod.compute_lift_progression(
            sex=sex,
            equipment=equipment,
            tested=tested,
            event=event,
            federation=federation,
            country=country,
            parent_federation=parent_federation,
            weight_class=weight_class,
            division=division,
            x_axis=x_axis,
        )
    )


@app.get("/api/lifters/search")
def api_lifters_search(
    q: str = Query(..., min_length=2),
    sex: str | None = Query(None),
    federation: str | None = Query(None),
    country: str | None = Query(DEFAULT_COUNTRY),
    parent_federation: str | None = Query(DEFAULT_PARENT_FEDERATION),
    equipment: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    return _clean(
        lifters_mod.search_lifters(
            q=q,
            sex=sex,
            federation=federation,
            country=country,
            parent_federation=parent_federation,
            equipment=equipment,
            limit=limit,
        )
    )


@app.get("/api/lifters/{name}/history")
def api_lifter_history(name: str) -> dict[str, Any]:
    return _clean(lifters_mod.get_lifter_history(name))


@app.post("/api/manual/trajectory")
def api_manual_trajectory(req: ManualTrajectoryRequest) -> dict[str, Any]:
    return _clean(build_manual_trajectory(req))


@app.get("/api/qt/blocks")
def api_qt_blocks(
    country: str = Query("Canada"),
    federation: str = Query("CPU"),
    equipment: str = Query("Raw"),
    tested: str = Query("Yes"),
    event: str = Query("SBD"),
) -> dict[str, Any]:
    """Four-block Open-only view for the QT tab.

    Returns keys F_Regionals, F_Nationals, M_Regionals, M_Nationals, each a
    list of {weight_class, pct_pre2025, pct_2025, pct_2027_today}.
    """
    return _clean(
        qt_mod.compute_blocks(
            country=country,
            federation=federation,
            equipment=equipment,
            tested=tested,
            event=event,
        )
    )
