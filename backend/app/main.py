"""FastAPI app entry point.

Run locally:
    cd cpu-analytics
    uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

import math
import os
import time
import traceback
from contextlib import asynccontextmanager
from typing import Any

import duckdb
from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware

from . import filters as filters_mod
from . import lifters as lifters_mod
from . import progression as progression_mod
from . import qt as qt_mod
from .data import OPENIPF_PARQUET, QT_PARQUET, get_cursor
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
        conn = get_cursor()
        # Touch each view so DuckDB actually opens the parquet, not just
        # records the parquet_scan SQL.
        n_meets = conn.execute("SELECT COUNT(*) FROM openipf").fetchone()[0]
        n_qt = conn.execute("SELECT COUNT(*) FROM qt_standards").fetchone()[0]
        # qt_current is optional; skipped if the view wasn't registered.
        from .data import is_qt_current_available
        if is_qt_current_available():
            n_qt_current = conn.execute("SELECT COUNT(*) FROM qt_current").fetchone()[0]
            print(
                f"[startup] warmed: openipf={n_meets:,} rows, "
                f"qt_standards={n_qt} rows, qt_current={n_qt_current} rows"
            )
        else:
            print(
                f"[startup] warmed: openipf={n_meets:,} rows, "
                f"qt_standards={n_qt} rows, qt_current=UNAVAILABLE "
                f"(live endpoints degraded)"
            )
        # Memory footprint after warmup. Visible in Render logs so future
        # regressions (accidental full-table .df() load, etc) are obvious.
        try:
            import psutil
            rss_mb = psutil.Process().memory_info().rss / 1024 / 1024
            print(f"[startup] process RSS: {rss_mb:.1f} MB")
        except ImportError:
            pass
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

# Gzip JSON responses. Cohort/qt payloads compress ~5-10x and dominate the
# wire time on Render's free tier.
app.add_middleware(GZipMiddleware, minimum_size=500)


# Request timing middleware: logs method + path + status + duration on every
# request, including errors. Makes slow endpoints and failure spikes obvious
# in Render logs.
@app.middleware("http")
async def log_request_duration(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        dur_ms = (time.perf_counter() - start) * 1000
        print(f"[req] {request.method} {request.url.path} CRASH in {dur_ms:.0f}ms")
        raise
    # Skip /api/health: uvicorn access-logs it, and UptimeRobot + Render's
    # internal prober would otherwise double-spam the app log every few seconds.
    if request.url.path == "/api/health":
        return response
    dur_ms = (time.perf_counter() - start) * 1000
    print(
        f"[req] {request.method} {request.url.path} "
        f"{response.status_code} {dur_ms:.0f}ms"
    )
    return response


# Dedicated handler for DuckDB errors: logs the path so we know which
# endpoint triggered the query failure, returns a user-safe 503 instead
# of leaking stack traces through FastAPI's default 500.
@app.exception_handler(duckdb.Error)
async def duckdb_error_handler(request: Request, exc: duckdb.Error):
    tb = traceback.format_exc()
    print(
        f"[duckdb-error] path={request.url.path} "
        f"type={type(exc).__name__} msg={exc!s}\n{tb}"
    )
    return JSONResponse(
        status_code=503,
        content={
            "error": "database_error",
            "message": "Temporary database error. Please retry in a moment.",
        },
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


_WEEKLY_CACHE_CONTROL = "public, max-age=300"


def _parquet_etag() -> str:
    """Weak ETag derived from parquet mtime. Flips on weekly data refresh."""
    try:
        mtime = max(
            int(OPENIPF_PARQUET.stat().st_mtime),
            int(QT_PARQUET.stat().st_mtime),
        )
        return f'W/"parquet-{mtime}"'
    except OSError:
        return 'W/"parquet-unknown"'


def _maybe_304(request: Request, response: Response) -> Response | None:
    """Set Cache-Control + ETag; return 304 Response on If-None-Match hit."""
    etag = _parquet_etag()
    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": _WEEKLY_CACHE_CONTROL},
        )
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = _WEEKLY_CACHE_CONTROL
    return None


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health() -> dict[str, str]:
    """Liveness probe. Answers GET or HEAD.

    UptimeRobot's free plan only supports HEAD, so accepting both prevents
    the 405 Method Not Allowed that was causing false outage alerts.
    FastAPI returns an empty body on HEAD automatically.
    """
    return {"status": "ok"}


@app.api_route("/api/ready", methods=["GET", "HEAD"])
def ready():
    """Readiness probe. Runs a tiny query to confirm DuckDB is live.

    Returns 200 with {'ready': true} on success, 503 otherwise. This is
    a stricter check than /api/health -- if the parquet views are
    unreadable (corrupt download, missing file, etc), this fails while
    /api/health still passes.
    """
    from fastapi import Response
    try:
        cur = get_cursor()
        cur.execute("SELECT 1").fetchone()
        return {"ready": True}
    except Exception as exc:
        return Response(
            content='{"ready": false, "error": "' + type(exc).__name__ + '"}',
            status_code=503,
            media_type="application/json",
        )


@app.get("/api/filters")
def api_filters(request: Request, response: Response) -> Any:
    cached = _maybe_304(request, response)
    if cached is not None:
        return cached
    return filters_mod.get_filters()


@app.get("/api/qt/standards")
def api_qt_standards(request: Request, response: Response) -> Any:
    cached = _maybe_304(request, response)
    if cached is not None:
        return cached
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
    metric: str = Query("total", description="Metric to track: 'total' (TotalKg), 'bodyweight' (BodyweightKg), or 'goodlift' (GLP score)."),
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
            metric=metric,
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
    # Newly accepted so per-lift view honors the full filter set the user
    # configures in the sidebar. Without these, per_lift silently ignored
    # tested, age_category, max_gap_months, and same_class_only.
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
    request: Request,
    response: Response,
    country: str = Query("Canada"),
    federation: str = Query("CPU"),
    equipment: str = Query("Raw"),
    tested: str = Query("Yes"),
    event: str = Query("SBD"),
    division: str = Query("Open", description="Age division for QT view."),
) -> Any:
    """Four-block view for the QT tab, scoped by age division.

    Returns keys F_Regionals, F_Nationals, M_Regionals, M_Nationals, each a
    list of {weight_class, pct_pre2025, pct_2025, pct_2027_today}. Plus a
    `meta` key with the selected division and a `using_open_fallback` flag
    the frontend reads to decide whether to show the "Open values shown,
    age-specific coming" banner.
    """
    from .data_static.qt_by_division import has_age_specific_qt

    cached = _maybe_304(request, response)
    if cached is not None:
        return cached
    blocks = qt_mod.compute_blocks(
        country=country,
        federation=federation,
        equipment=equipment,
        tested=tested,
        event=event,
        division=division,
    )
    return _clean(
        {
            **blocks,
            "meta": {
                "division": division,
                "using_open_fallback": not has_age_specific_qt(division),
            },
        }
    )


# =========================================================================
# Live-scrape QT endpoints (2026+)
#
# These serve the qualifying totals scraped weekly from powerlifting.ca
# (see data/scrapers/cpu.py and .github/workflows/qt_refresh.yml). The
# older /api/qt/coverage and /api/qt/blocks endpoints above keep serving
# the historical pre-2025 / 2025 values from qt_standards.parquet.
# =========================================================================


@app.get("/api/qt/live/filters")
def api_qt_live_filters(request: Request, response: Response) -> Any:
    """Available filter values for the live-scrape QT view.

    Returns ``{live_data_available: bool, sexes, levels, regions,
    divisions, effective_years, fetched_at}``. When live data is not
    available (scraper hasn't run yet, or CSV unreachable), only
    ``live_data_available: false`` is returned and the frontend should
    hide or disable the live filter panel.
    """
    cached = _maybe_304(request, response)
    if cached is not None:
        return cached
    return _clean(qt_mod.get_live_qt_filters())


@app.get("/api/qt/live/coverage")
def api_qt_live_coverage(
    request: Request,
    response: Response,
    sex: str = Query(..., description="M or F"),
    level: str = Query(..., description="Nationals or Regionals"),
    effective_year: int = Query(..., description="e.g. 2026 or 2027"),
    division: str = Query("Open"),
    region: str | None = Query(
        None,
        description="Western/Central, Eastern, or omit for pre-2027 Regionals",
    ),
    equipment: str = Query("Classic"),
    event: str = Query("SBD"),
) -> Any:
    """Per-weight-class coverage for one live-QT slice.

    Cohort: lifters in the Canada+IPF+CPU scope whose best SBD total
    in the 24 months ending March 1 of ``effective_year`` matches the
    requested filters. Response shape::

        {
            "rows": [
                {"weight_class": "83", "qt": 700.0, "n_lifters": 142,
                 "n_meeting_qt": 6, "pct_meeting_qt": 4.23},
                ...
            ],
            "meta": {
                "live_data_available": bool,
                "filters": {...the parameters the request used...},
                "fetched_at": "<iso>" | null,
            },
        }
    """
    cached = _maybe_304(request, response)
    if cached is not None:
        return cached

    if not qt_mod.is_qt_current_available():
        return _clean({
            "rows": [],
            "meta": {
                "live_data_available": False,
                "filters": {
                    "sex": sex, "level": level, "effective_year": effective_year,
                    "division": division, "region": region,
                    "equipment": equipment, "event": event,
                },
                "fetched_at": None,
            },
        })

    df = qt_mod.compute_live_coverage(
        sex=sex,
        level=level,
        effective_year=effective_year,
        division=division,
        region=region,
        equipment=equipment,
        event=event,
    )
    rows = df.to_dict(orient="records") if not df.empty else []

    # Pull fetched_at from any matching qt_current row so the UI can
    # display "data last updated YYYY-MM-DD".
    filters_meta = qt_mod.get_live_qt_filters()
    return _clean({
        "rows": rows,
        "meta": {
            "live_data_available": True,
            "filters": {
                "sex": sex, "level": level, "effective_year": effective_year,
                "division": division, "region": region,
                "equipment": equipment, "event": event,
            },
            "fetched_at": filters_meta.get("fetched_at"),
        },
    })
