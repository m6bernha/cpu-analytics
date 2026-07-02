"""FastAPI app entry point.

Run locally:
    cd cpu-analytics
    uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

import logging
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

log = logging.getLogger(__name__)

# Configure logging for the app and all uvicorn-managed loggers.
# Uvicorn doesn't configure the root logger, so app loggers default to
# NOTSET level and would not emit without this basicConfig.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

from . import athlete_projection as athlete_proj_mod
from . import filters as filters_mod
from . import lifters as lifters_mod
from . import meta as meta_mod
from . import progression as progression_mod
from . import qt as qt_mod
from .data import ATHLETE_PROJ_TABLES, OPENIPF_PARQUET, QT_PARQUET, get_cursor
from .data_loader import ensure_athlete_proj_tables
from .manual import ManualTrajectoryRequest, build_manual_trajectory
from .scope import DEFAULT_COUNTRY, DEFAULT_PARENT_FEDERATION
from .scout import ScoutMeetRequest, build_scout_report


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
            log.info(
                "[startup] warmed: openipf=%d rows, qt_standards=%d rows, qt_current=%d rows",
                n_meets, n_qt, n_qt_current
            )
        else:
            log.info(
                "[startup] warmed: openipf=%d rows, qt_standards=%d rows, "
                "qt_current=UNAVAILABLE (live endpoints degraded)",
                n_meets, n_qt
            )
        # Memory footprint after warmup. Visible in Render logs so future
        # regressions (accidental full-table .df() load, etc) are obvious.
        try:
            import psutil
            rss_mb = psutil.Process().memory_info().rss / 1024 / 1024
            log.info("[startup] process RSS: %.1f MB", rss_mb)
        except ImportError:
            pass
        # Athlete Projection cohort + Kaplan-Meier tables. Populates
        # module-level state so per-request projection endpoints never
        # run a cohort fit.
        #
        # Fast path: preprocess.py writes a serialized artifact
        # (athlete_projection_tables.json) alongside openipf.parquet and
        # ships it in the data-latest release. Loading the artifact is a
        # ~ms operation vs the ~27 s cost of live fitting. The artifact
        # is versioned (SERIALIZED_TABLES_SCHEMA_VERSION); a mismatch or
        # any load error falls through to the live-fit slow path.
        if n_meets > 0:
            import time
            stats: dict[str, int] | None = None
            have_artifact = ensure_athlete_proj_tables(ATHLETE_PROJ_TABLES)
            if have_artifact:
                t_load = time.perf_counter()
                try:
                    stats = athlete_proj_mod.load_serialized_tables(
                        ATHLETE_PROJ_TABLES,
                    )
                    load_ms = 1000.0 * (time.perf_counter() - t_load)
                    log.info(
                        "[startup] athlete_projection tables: loaded from disk "
                        "cohort_cells=%d km=%d mixedlm_cells=%d elapsed_ms=%.0f",
                        stats['cohort_cells'], stats['km_tables'],
                        stats.get('mixedlm_cells', 0), load_ms
                    )
                except Exception as exc:
                    log.warning(
                        "[startup] athlete_projection artifact load failed: "
                        "%r -- falling back to live fit",
                        exc
                    )
                    stats = None
            if stats is None:
                t_precompute = time.perf_counter()
                stats = athlete_proj_mod.precompute_tables(conn)
                precompute_ms = 1000.0 * (time.perf_counter() - t_precompute)
                log.info(
                    "[startup] athlete_projection tables: fitted "
                    "cohort_cells=%d km=%d mixedlm_cells=%d elapsed_ms=%.0f",
                    stats['cohort_cells'], stats['km_tables'],
                    stats.get('mixedlm_cells', 0), precompute_ms
                )
            # Engine D global gate: log the convergence rate + flag for
            # operators. The flag is already set by load/precompute; this
            # line is the operator-visible signal in Render logs.
            mixedlm_pct = stats.get("mixedlm_converged_pct", 0.0) or 0.0
            log.info(
                "[startup] engine_d gate: rate=%.3f available=%s",
                mixedlm_pct, athlete_proj_mod.is_engine_d_globally_available()
            )
        # If either view is empty, the parquet is likely corrupt or truncated.
        # Delete the files so the next cold-start re-downloads, then log.
        if n_meets == 0 or n_qt == 0:
            import os
            from .data import OPENIPF_PARQUET, QT_PARQUET
            log.error(
                "[startup] ERROR: parquet appears empty (openipf=%d, qt=%d). "
                "Removing local files so the next cold-start re-downloads.",
                n_meets, n_qt
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
        log.warning("[startup] warmup failed: %r", exc)
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
        log.error("[req] %s %s CRASH in %.0f ms", request.method, request.url.path, dur_ms)
        raise
    # Skip /api/health: uvicorn access-logs it, and UptimeRobot + Render's
    # internal prober would otherwise double-spam the app log every few seconds.
    if request.url.path == "/api/health":
        return response
    dur_ms = (time.perf_counter() - start) * 1000
    log.info("[req] %s %s %d %.0f ms", request.method, request.url.path, response.status_code, dur_ms)
    return response


# Dedicated handler for DuckDB errors: logs the path so we know which
# endpoint triggered the query failure, returns a user-safe 503 instead
# of leaking stack traces through FastAPI's default 500.
@app.exception_handler(duckdb.Error)
async def duckdb_error_handler(request: Request, exc: duckdb.Error):
    log.error(
        "[duckdb-error] path=%s type=%s msg=%s",
        request.url.path, type(exc).__name__, exc,
        exc_info=True
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
    try:
        cur = get_cursor()
        cur.execute("SELECT 1").fetchone()
        return {"ready": True}
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "error": type(exc).__name__},
        )


@app.get("/api/meta/freshness")
def api_meta_freshness(request: Request, response: Response) -> Any:
    """Data-freshness metadata for the header badge.

    Returns the latest meet date present in the openipf view plus the
    row count. Cheap (container-lifetime cached) and ETag-friendly.
    """
    cached = _maybe_304(request, response)
    if cached is not None:
        return cached
    return meta_mod.get_freshness()


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


@app.post("/api/scout/report")
def api_scout_report(req: ScoutMeetRequest) -> dict[str, Any]:
    """Generate a Vireo-style meet scouting report from a roster.

    Manual roster paste only (no SimplMeet/LiftingCast scrapers in v1).
    Fans out to search_lifters() + shrinkage_projection() per athlete,
    groups by canonical weight class, and sorts classes by ascending
    projected #1-vs-#2 gap.

    See `backend/app/scout.py` for the model definitions and
    `NEXT_STEPS.md` P7 "Meet scouting report generator" for the
    phased rollout plan.
    """
    return _clean(build_scout_report(req).model_dump())


# =========================================================================
# Live-scrape QT endpoints (2026+)
#
# These serve the qualifying totals scraped weekly from powerlifting.ca
# (see data/scrapers/cpu.py and .github/workflows/qt_refresh.yml). The
# older /api/qt/coverage endpoint above keeps serving the historical
# pre-2025 / 2025 values from qt_standards.parquet.
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
    level: str = Query(..., description="Nationals, Regionals, or Provincials"),
    effective_year: int = Query(..., description="e.g. 2026 or 2027"),
    division: str = Query("Open"),
    region: str | None = Query(
        None,
        description="Western/Central, Eastern, or omit for pre-2027 Regionals",
    ),
    province: str | None = Query(
        None,
        description="required when level=Provincials (e.g. Ontario)",
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

    filters_echo = {
        "sex": sex, "level": level, "effective_year": effective_year,
        "division": division, "region": region, "province": province,
        "equipment": equipment, "event": event,
    }

    if not qt_mod.is_qt_current_available():
        return _clean({
            "rows": [],
            "meta": {
                "live_data_available": False,
                "filters": filters_echo,
                "fetched_at": None,
            },
        })

    df = qt_mod.compute_live_coverage(
        sex=sex,
        level=level,
        effective_year=effective_year,
        division=division,
        region=region,
        province=province,
        equipment=equipment,
        event=event,
    )
    rows = df.to_dict(orient="records") if not df.empty else []

    filters_meta = qt_mod.get_live_qt_filters()
    return _clean({
        "rows": rows,
        "meta": {
            "live_data_available": True,
            "filters": filters_echo,
            "fetched_at": filters_meta.get("fetched_at"),
        },
    })


# ---------------------------------------------------------------------------
# Athlete Projection (BETA) -- per-lift Engine C / Engine D
# ---------------------------------------------------------------------------


@app.get("/api/athlete/{name}/projection")
def api_athlete_projection(
    name: str,
    engine: str = Query(
        "shrinkage",
        description="Projection engine: 'shrinkage' (default) or 'mixed_effects'.",
    ),
    horizon: int = Query(
        12,
        ge=1,
        le=24,
        description="Projection horizon in months. Server may clamp to 18 (hard) or 6 (small-N).",
    ),
    n_points: int = Query(
        6,
        ge=2,
        le=12,
        description="Number of points to draw along the projection curve.",
    ),
) -> dict[str, Any]:
    """Per-lift projection for a named lifter.

    `engine=shrinkage` is the shipping default. `engine=mixed_effects`
    activates Engine D (MixedLM-derived cohort term, per-lift Engine C
    fallback when a cell did not converge) when the global gate is on.
    Frontend availability is exposed via /api/athlete/projection-engines.
    """
    if engine == "mixed_effects":
        result = athlete_proj_mod.mixed_effects_projection(
            lifter_name=name, horizon_months=horizon, n_points=n_points,
        )
    else:
        result = athlete_proj_mod.shrinkage_projection(
            lifter_name=name, horizon_months=horizon, n_points=n_points,
        )
    if result is None:
        return {
            "found": False,
            "lifter_name": name,
            "reason": "no_meets_or_missing_age",
        }
    payload = athlete_proj_mod.to_response_dict(result)
    payload["found"] = True
    return _clean(payload)


@app.get("/api/athlete/projection-engines")
def api_projection_engines() -> dict[str, Any]:
    """Expose which projection engines are currently available to clients.

    Engine C (`shrinkage`) is always available. Engine D (`mixed_effects`)
    is gated on the live precompute clearing >= 70% MixedLM convergence
    rate (see `ENGINE_D_GLOBAL_GATE_THRESHOLD` in athlete_projection.py).
    Frontend uses this to decide whether to show the Simple/Advanced
    engine toggle on the Athlete Projection tab.
    """
    return {
        "shrinkage": {"available": True},
        "mixed_effects": {
            "available": athlete_proj_mod.is_engine_d_globally_available(),
            "convergence_rate": athlete_proj_mod.get_mixedlm_converged_pct(),
            "n_cells": athlete_proj_mod.get_mixedlm_cell_count(),
        },
    }
