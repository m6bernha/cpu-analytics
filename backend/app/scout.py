"""Meet scouting report generator (Vireo-style).

Builds a per-meet scouting brief from a roster of lifter names. Reuses
the existing search_lifters() to resolve names against OpenIPF and the
existing shrinkage_projection() to project each matched lifter forward
to meet day. Aggregates into class blocks sorted by projected #1-vs-#2
gap so coaches can see the tightest battles first.

MVP scope (locked 2026-05-19):
- Manual roster paste only (no scrapers).
- Canada+IPF scope inherited from scope.py via the projection helper.
- 95% PI summed in quadrature across S/B/D.

See `~/.claude/plans/project-audit-and-status-majestic-pretzel.md` for the
full design and `~/.claude/plans/where-did-we-leave-elegant-sifakis.md`
for the implementation sprint context.
"""

from __future__ import annotations

from datetime import date, datetime
from math import ceil, sqrt
from typing import Any, Literal

from pydantic import BaseModel, Field

from .athlete_projection import shrinkage_projection
from .lifters import search_lifters


StatusTag = Literal[
    "Rookie",
    "Developing",
    "Established",
    "Veteran",
    "Frozen",
    "Unmatched",
]


# ---------------------------------------------------------------------------
# Request models (Pydantic for FastAPI surface)
# ---------------------------------------------------------------------------


class ScoutManualOverride(BaseModel):
    """User-supplied data for a lifter not present in OpenIPF."""

    best_total_kg: float = Field(..., ge=0, le=1500)
    squat_best_kg: float | None = Field(None, ge=0, le=600)
    bench_best_kg: float | None = Field(None, ge=0, le=400)
    deadlift_best_kg: float | None = Field(None, ge=0, le=600)
    weight_class: str | None = Field(None, max_length=20)
    sex: str | None = Field(None, pattern=r"^[MF]$")
    last_meet_date: str | None = Field(
        None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="ISO date of the last competitive meet.",
    )


class ScoutRosterEntry(BaseModel):
    """One athlete in the roster."""

    name: str = Field(..., min_length=1, max_length=120)
    is_homie: bool = False
    manual_override: ScoutManualOverride | None = None


class ScoutMeetRequest(BaseModel):
    """Top-level request body for `POST /api/scout/report`."""

    meet_name: str = Field(..., min_length=1, max_length=200)
    federation: str = Field("CPU", max_length=50)
    location: str = Field("", max_length=200)
    meet_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="ISO date of the meet (YYYY-MM-DD).",
    )
    generator_name: str = Field("", max_length=100)
    generator_brand: str = Field("", max_length=100)
    roster: list[ScoutRosterEntry] = Field(..., min_length=1, max_length=500)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ScoutAthleteRow(BaseModel):
    name: str
    is_homie: bool
    is_manual: bool                          # True when sourced from manual override
    status_tag: StatusTag
    division: str | None                     # CPU age division string
    weight_class: str | None
    n_meets: int | None
    best_total_kg: float | None
    squat_best_kg: float | None
    bench_best_kg: float | None
    deadlift_best_kg: float | None
    last_meet_date: str | None
    days_since_last_meet: int | None
    projected_total_kg: float | None
    projected_pi_half_kg: float | None       # quadrature half-width across S/B/D
    glp_score: float | None
    inline_tags: list[str]


class ScoutClassBlock(BaseModel):
    weight_class: str | None
    n_athletes: int
    projected_gap_kg: float | None           # #1 - #2 among "active" athletes
    athletes: list[ScoutAthleteRow]          # sorted by projected_total desc


class ScoutMeetReport(BaseModel):
    request: ScoutMeetRequest
    horizon_days: int
    horizon_months: int
    generated_at: str
    class_blocks: list[ScoutClassBlock]
    homies: list[ScoutAthleteRow]
    closest_battles: list[ScoutClassBlock]   # top N classes sorted by smallest gap
    unranked: list[str]
    methodology: str
    n_athletes_matched: int


# ---------------------------------------------------------------------------
# Constants + helpers
# ---------------------------------------------------------------------------


STALE_DAYS_THRESHOLD = 730                   # > 2 years since last meet = stale
CLOSEST_BATTLES_TOP_N = 5
DAYS_PER_MONTH = 30.44

_METHODOLOGY_TEXT = (
    "Projections use Engine C (Bayesian shrinkage with IPF-GL-stratified "
    "cohort slopes) summed across squat, bench, and deadlift to horizon = "
    "meet day. 95% prediction intervals are quadrature-summed per lift "
    "(sqrt of sum of squared half-widths). Class ordering: ascending by "
    "projected #1-vs-#2 gap; stale lifters (>2 yr since last meet) are "
    "shown but excluded from the gap calc. Status tags derive from meet "
    "count and tenure days. Lifters not found in OpenIPF appear under the "
    "Unranked Field section. Coverage: Canadian IPF-affiliated meets only. "
    "Not affiliated with the CPU or IPF."
)


def classify_status(
    n_meets: int | None,
    tenure_days: int | None,
) -> StatusTag:
    """Map (n_meets, tenure_days) -> status tag.

    Cutoffs per `project-audit-and-status-majestic-pretzel.md`:
      Frozen:      n_meets == 1 (no slope estimable)
      Rookie:      n_meets <= 3 OR tenure < 1 yr
      Developing:  4 <= n_meets <= 7 AND 1-3 yr tenure
      Established: 8 <= n_meets <= 19 AND 3-7 yr tenure
      Veteran:     n_meets >= 20 OR tenure >= 7 yr
    Falls through to closest match for in-between combinations.
    """
    if n_meets is None:
        return "Unmatched"
    if n_meets == 1:
        return "Frozen"
    if tenure_days is None:
        return "Frozen"

    tenure_years = tenure_days / 365.25

    if n_meets >= 20 or tenure_years >= 7:
        return "Veteran"
    if n_meets <= 3 or tenure_years < 1:
        return "Rookie"
    if 8 <= n_meets <= 19 and 3 <= tenure_years <= 7:
        return "Established"
    if 4 <= n_meets <= 7 and 1 <= tenure_years <= 3:
        return "Developing"
    # In-between fallback: bias to the n_meets reading
    if n_meets <= 7:
        return "Developing"
    return "Established"


def _quadrature_half_width(half_widths: list[float | None]) -> float | None:
    """Quadrature sum of half-widths; returns None if all entries are None."""
    valid = [w for w in half_widths if w is not None]
    if not valid:
        return None
    return round(sqrt(sum(w * w for w in valid)), 1)


def _flatten_meta_tags(meta: dict[str, Any]) -> list[str]:
    """Convert projection-response `meta.*` flags into a flat tag list."""
    tags: list[str] = []
    if meta.get("small_n_warning"):
        tags.append("small-N warning")
    if meta.get("long_horizon_warning"):
        tags.append("long-horizon warning")
    transitions = meta.get("bracket_transitions") or 0
    if transitions:
        tags.append(f"bracket transitions: {transitions}")
    fallback_lifts = meta.get("engine_d_fallback_lifts") or []
    if fallback_lifts:
        tags.append(f"engine-D fallback: {', '.join(fallback_lifts)}")
    if meta.get("engine_d_partial"):
        tags.append("engine-D partial fit")
    return tags


def _ms_to_iso(value: Any) -> str | None:
    """Best-effort ISO YYYY-MM-DD from various date-like inputs."""
    if value is None:
        return None
    s = str(value)
    if len(s) >= 10:
        return s[:10]
    return None


def _days_between(iso_a: str, iso_b: str) -> int | None:
    try:
        a = datetime.strptime(iso_a, "%Y-%m-%d").date()
        b = datetime.strptime(iso_b, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (b - a).days


# ---------------------------------------------------------------------------
# Per-athlete row construction
# ---------------------------------------------------------------------------


def _row_from_override(
    entry: ScoutRosterEntry,
    today_iso: str,
) -> ScoutAthleteRow:
    """Build a row from a user-supplied manual override.

    Used when the roster name is not found in OpenIPF but the user provided
    enough data to include the athlete in the report anyway. No projection;
    best_total stands as a coarse forecast.
    """
    o = entry.manual_override
    assert o is not None, "_row_from_override called without override"

    last_iso = o.last_meet_date
    days_since = _days_between(last_iso, today_iso) if last_iso else None
    status = "Frozen" if days_since is None else "Established"

    return ScoutAthleteRow(
        name=entry.name,
        is_homie=entry.is_homie,
        is_manual=True,
        status_tag=status,
        division=None,
        weight_class=o.weight_class,
        n_meets=None,
        best_total_kg=o.best_total_kg,
        squat_best_kg=o.squat_best_kg,
        bench_best_kg=o.bench_best_kg,
        deadlift_best_kg=o.deadlift_best_kg,
        last_meet_date=last_iso,
        days_since_last_meet=days_since,
        projected_total_kg=o.best_total_kg,
        projected_pi_half_kg=None,
        glp_score=None,
        inline_tags=["manual entry"],
    )


def _row_from_openipf(
    entry: ScoutRosterEntry,
    search_row: dict[str, Any],
    horizon_months: int,
    today_iso: str,
) -> ScoutAthleteRow:
    """Project a matched OpenIPF lifter forward to meet day, build the row.

    `search_row` is one record from `search_lifters()`; supplies LatestMeetDate,
    LatestWeightClass, BestTotalKg, MeetCount, Sex. The projection call adds
    division, current S/B/D levels, projected_total_kg, PI quadrature, GLP,
    and inline tags.
    """
    name = str(search_row.get("Name") or entry.name)
    last_iso = _ms_to_iso(search_row.get("LatestMeetDate"))
    days_since = _days_between(last_iso, today_iso) if last_iso else None
    n_meets = int(search_row.get("MeetCount") or 0) or None
    best_total = search_row.get("BestTotalKg")
    best_total = float(best_total) if best_total is not None else None
    weight_class = search_row.get("LatestWeightClass")
    weight_class = str(weight_class) if weight_class is not None else None

    # Project forward to meet day. None means insufficient data (no
    # cohort cell, no age, etc.) — fall back to a frozen-style row.
    proj = shrinkage_projection(
        lifter_name=name,
        horizon_months=max(1, horizon_months),
    )
    if proj is None:
        return ScoutAthleteRow(
            name=name,
            is_homie=entry.is_homie,
            is_manual=False,
            status_tag=classify_status(n_meets, _tenure_days(search_row, today_iso)),
            division=None,
            weight_class=weight_class,
            n_meets=n_meets,
            best_total_kg=best_total,
            squat_best_kg=None,
            bench_best_kg=None,
            deadlift_best_kg=None,
            last_meet_date=last_iso,
            days_since_last_meet=days_since,
            projected_total_kg=best_total,
            projected_pi_half_kg=None,
            glp_score=None,
            inline_tags=["projection unavailable"],
        )

    # Aggregate per-lift projected totals + PI quadrature.
    projected_kgs: list[float] = []
    pi_half_widths: list[float | None] = []
    sbd_best: dict[str, float | None] = {"squat": None, "bench": None, "deadlift": None}
    for lift_key in ("squat", "bench", "deadlift"):
        lp = proj.lifts.get(lift_key)
        if lp is None or not lp.projected_points:
            pi_half_widths.append(None)
            continue
        last_pt = lp.projected_points[-1]
        pkg = last_pt.get("projected_kg")
        if pkg is not None:
            projected_kgs.append(float(pkg))
        upper = last_pt.get("upper_kg")
        lower = last_pt.get("lower_kg")
        if upper is not None and lower is not None:
            pi_half_widths.append((float(upper) - float(lower)) / 2.0)
        else:
            pi_half_widths.append(None)
        sbd_best[lift_key] = (
            float(lp.current_level) if lp.current_level is not None else None
        )

    projected_total = round(sum(projected_kgs), 1) if projected_kgs else None
    pi_quad = _quadrature_half_width(pi_half_widths)

    glp = None
    bracket_meta = proj.meta.get("lifter_bracket") or {}
    glp_raw = bracket_meta.get("glp_score")
    if glp_raw is not None:
        glp = round(float(glp_raw), 1)

    tenure = _tenure_days(search_row, today_iso, fallback_history=proj.total_history)
    status = classify_status(n_meets, tenure)

    return ScoutAthleteRow(
        name=name,
        is_homie=entry.is_homie,
        is_manual=False,
        status_tag=status,
        division=proj.age_division,
        weight_class=weight_class,
        n_meets=n_meets,
        best_total_kg=best_total,
        squat_best_kg=sbd_best["squat"],
        bench_best_kg=sbd_best["bench"],
        deadlift_best_kg=sbd_best["deadlift"],
        last_meet_date=last_iso,
        days_since_last_meet=days_since,
        projected_total_kg=projected_total,
        projected_pi_half_kg=pi_quad,
        glp_score=glp,
        inline_tags=_flatten_meta_tags(proj.meta),
    )


def _tenure_days(
    search_row: dict[str, Any],
    today_iso: str,
    fallback_history: tuple[dict[str, Any], ...] | None = None,
) -> int | None:
    """Estimate tenure_days from the projection's history if available.

    Falls back to None when we have no first-meet date. search_lifters only
    returns the LATEST meet date, so we use the projection's total_history
    when present.
    """
    if fallback_history:
        first = fallback_history[0]
        first_iso = _ms_to_iso(first.get("date"))
        if first_iso:
            return _days_between(first_iso, today_iso)
    return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _exact_match(name: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the highest-best-total row whose Name matches exactly (case-insensitive)."""
    needle = name.strip().lower()
    for r in rows:
        if str(r.get("Name", "")).strip().lower() == needle:
            return r
    return None


def build_scout_report(req: ScoutMeetRequest) -> ScoutMeetReport:
    """Build the report from a meet-request envelope.

    Steps:
      1. Compute horizon_days / horizon_months from meet_date - today.
      2. For each roster entry: exact-match in search_lifters; if matched,
         project and build a row. If not matched but a manual override is
         provided, build a manual row. Else add to unranked.
      3. Group by weight class. Sort classes by smallest projected gap
         (active athletes only). Closest battles = top N.
    """
    today_iso = date.today().isoformat()
    try:
        meet_dt = datetime.strptime(req.meet_date, "%Y-%m-%d").date()
        horizon_days = max((meet_dt - date.today()).days, 0)
    except ValueError:
        horizon_days = 0
    horizon_months = max(1, ceil(horizon_days / DAYS_PER_MONTH)) if horizon_days else 1

    matched_rows: list[ScoutAthleteRow] = []
    unranked: list[str] = []

    for entry in req.roster:
        search_rows = search_lifters(q=entry.name, limit=20)
        match = _exact_match(entry.name, search_rows)
        if match is not None:
            matched_rows.append(
                _row_from_openipf(entry, match, horizon_months, today_iso)
            )
        elif entry.manual_override is not None:
            matched_rows.append(_row_from_override(entry, today_iso))
        else:
            unranked.append(entry.name)

    # Group by weight_class. None-class rows go in their own bucket.
    class_groups: dict[str | None, list[ScoutAthleteRow]] = {}
    for r in matched_rows:
        class_groups.setdefault(r.weight_class, []).append(r)

    class_blocks: list[ScoutClassBlock] = []
    for cls, athletes in class_groups.items():
        athletes_sorted = sorted(
            athletes,
            key=lambda a: (
                a.projected_total_kg if a.projected_total_kg is not None else -1
            ),
            reverse=True,
        )
        # Active = not stale (>2yr) AND has a numeric projection
        active = [
            a for a in athletes_sorted
            if a.projected_total_kg is not None
            and (a.days_since_last_meet or 0) <= STALE_DAYS_THRESHOLD
        ]
        gap_kg: float | None = None
        if len(active) >= 2:
            gap_kg = round(
                float(active[0].projected_total_kg) - float(active[1].projected_total_kg),
                1,
            )
        class_blocks.append(ScoutClassBlock(
            weight_class=cls,
            n_athletes=len(athletes),
            projected_gap_kg=gap_kg,
            athletes=athletes_sorted,
        ))

    # Sort by smallest gap first; None last (no head-to-head to predict).
    def _gap_sort_key(cb: ScoutClassBlock) -> tuple[int, float, str]:
        if cb.projected_gap_kg is None:
            return (1, 0.0, str(cb.weight_class or ""))
        return (0, cb.projected_gap_kg, str(cb.weight_class or ""))

    class_blocks.sort(key=_gap_sort_key)

    closest_battles = [
        cb for cb in class_blocks if cb.projected_gap_kg is not None
    ][:CLOSEST_BATTLES_TOP_N]

    homies = [r for r in matched_rows if r.is_homie]

    return ScoutMeetReport(
        request=req,
        horizon_days=horizon_days,
        horizon_months=horizon_months,
        generated_at=today_iso,
        class_blocks=class_blocks,
        homies=homies,
        closest_battles=closest_battles,
        unranked=unranked,
        n_athletes_matched=len(matched_rows),
        methodology=_METHODOLOGY_TEXT,
    )
