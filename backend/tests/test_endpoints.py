"""HTTP-layer tests for every API endpoint.

The query modules underneath these routes are well covered already. The
routes themselves were not: before this file, 15 of 19 endpoints had no
test that went through FastAPI at all. Everything between the module
function and the client was therefore unverified -- status codes, query
parameter validation, response envelope, and the headers the app sets on
purpose.

That gap matters most for the handful of behaviours that exist BECAUSE
something broke once, and that fail silently if they regress:

  * `/api/health` answers HEAD. UptimeRobot's free plan is HEAD-only, and
    the keepalive cron is the only thing preventing Render's 15-minute
    spindown. Regress this to GET-only and nothing fails loudly: the pings
    just start 405-ing and users meet a ~50 s cold start instead.
  * ETag / If-None-Match returns 304. The ETag is derived from parquet
    mtime so it flips exactly once a week on the data refresh.
  * A `duckdb.Error` becomes a clean 503 `{"error": "database_error"}`
    rather than a 500 with a stack trace.
  * The rate limiter is registered INSIDE CORS, so a 429 still carries
    CORS headers. Get that order wrong and the browser reports an opaque
    network error instead of "too many requests" (see test_rate_limit.py,
    which owns the limiter's own behaviour).

Data comes from the synthetic fixture in conftest.py: lifters Alice A
(F, 3 SBD meets 2022-2025) and Bob B (M, 4 SBD meets 2022-2025), meets
"Ontario Champs" and "BC Open".
"""

from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(test_conn):
    from backend.app.main import app

    return TestClient(app)


@pytest.fixture(scope="module")
def raw_client(test_conn):
    """A client that returns the error response instead of re-raising.

    TestClient defaults to `raise_server_exceptions=True`, which re-raises
    anything reaching ServerErrorMiddleware. That hides responses produced
    by registered exception handlers, so asserting on the app's own error
    envelope needs this instead.
    """
    from backend.app.main import app

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


class TestProbes:
    def test_health_answers_get(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_health_answers_head(self, client):
        """UptimeRobot's free plan only sends HEAD.

        This is the keepalive path that stops the Render free tier from
        spinning down, and losing it is invisible: the monitor starts
        recording 405s while the site simply gets slow.
        """
        r = client.head("/api/health")
        assert r.status_code == 200, "HEAD must not 405, see docstring"

    def test_ready_answers_get_and_head(self, client):
        assert client.get("/api/ready").json() == {"ready": True}
        assert client.head("/api/ready").status_code == 200

    def test_ready_reports_503_when_duckdb_is_unreachable(self, client, monkeypatch):
        """`/api/ready` is a real readiness probe, not an alias for health.

        If the parquet views are unreadable, this must fail while
        `/api/health` keeps passing, so an orchestrator can tell "process
        is alive" from "process can serve".
        """
        def boom():
            raise duckdb.Error("simulated broken view")

        monkeypatch.setattr("backend.app.main.get_cursor", boom)
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["ready"] is False
        assert client.get("/api/health").status_code == 200


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


ETAGGED_PATHS = [
    "/api/meta/freshness",
    "/api/filters",
    "/api/qt/standards",
]


class TestCaching:
    @pytest.mark.parametrize("path", ETAGGED_PATHS)
    def test_sets_etag_and_cache_control(self, client, path):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["ETag"].startswith('W/"parquet-')
        assert "max-age" in r.headers["Cache-Control"]

    @pytest.mark.parametrize("path", ETAGGED_PATHS)
    def test_matching_if_none_match_returns_304(self, client, path):
        etag = client.get(path).headers["ETag"]
        r = client.get(path, headers={"If-None-Match": etag})
        assert r.status_code == 304
        assert r.headers["ETag"] == etag
        assert not r.content

    def test_stale_if_none_match_returns_a_fresh_200(self, client):
        r = client.get(
            "/api/filters", headers={"If-None-Match": 'W/"parquet-0"'},
        )
        assert r.status_code == 200
        assert r.json()


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    def test_duckdb_error_becomes_a_clean_503(self, raw_client, monkeypatch):
        """A driver error must not leak a 500 and a stack trace.

        The dedicated handler exists so the frontend can tell a database
        outage apart from a bug, and so the request path gets logged.
        """
        def boom():
            raise duckdb.Error("simulated query failure")

        monkeypatch.setattr("backend.app.main.filters_mod.get_filters", boom)
        r = raw_client.get("/api/filters")
        assert r.status_code == 503
        body = r.json()
        assert body["error"] == "database_error"
        # The driver's message must not reach the client.
        assert "simulated query failure" not in r.text

    def test_unknown_path_is_404(self, client):
        assert client.get("/api/does-not-exist").status_code == 404


# ---------------------------------------------------------------------------
# Read endpoints: happy path plus a rejected input
# ---------------------------------------------------------------------------


class TestFilters:
    def test_returns_populated_filter_arrays(self, client):
        body = client.get("/api/filters").json()
        assert body["sex"]
        assert body["weight_class"]
        assert body["x_axis"]


class TestQt:
    def test_standards_returns_rows(self, client):
        body = client.get("/api/qt/standards").json()
        assert isinstance(body, list) and body

    def test_coverage_happy_path(self, client):
        r = client.get("/api/qt/coverage")
        assert r.status_code == 200

    def test_live_filters_reports_availability(self, client):
        body = client.get("/api/qt/live/filters").json()
        # The fixture ships a qt_current CSV, so the live feed is present.
        # When it is absent the app degrades rather than erroring, which is
        # what `live_data_available` exists to signal.
        assert body["live_data_available"] is True
        assert 2026 in body["effective_years"]

    def test_live_filters_degrades_when_the_feed_is_missing(self, client, monkeypatch):
        monkeypatch.setattr(
            "backend.app.main.qt_mod.get_live_qt_filters",
            lambda: {"live_data_available": False, "sexes": [], "levels": [],
                     "regions": [], "provinces": [], "divisions": [],
                     "effective_years": [], "fetched_at": None},
        )
        body = client.get("/api/qt/live/filters").json()
        assert body["live_data_available"] is False

    def test_live_coverage_happy_path(self, client):
        r = client.get(
            "/api/qt/live/coverage",
            params={"sex": "M", "level": "Nationals", "effective_year": 2026},
        )
        assert r.status_code == 200
        assert r.json()["rows"]


class TestProgression:
    def test_happy_path(self, client):
        body = client.get("/api/cohort/progression", params={"sex": "F"}).json()
        assert "points" in body

    def test_rejects_an_unknown_x_axis(self, client):
        """Regression: this returned a 500 with a stack trace until
        2026-08-09.

        `compute_progression` raises a bare ValueError for an unknown axis,
        which is correct at the module level, but nothing translated it and
        the route is a public GET.
        """
        r = client.get("/api/cohort/progression", params={"x_axis": "Furlongs"})
        assert r.status_code == 422
        assert "Furlongs" in r.json()["detail"]

    def test_rejects_an_unknown_metric(self, client):
        r = client.get("/api/cohort/progression", params={"metric": "vibes"})
        assert r.status_code == 422

    def test_accepts_every_advertised_x_axis(self, client):
        """The filters endpoint advertises the axis list, so every value it
        offers has to be one this endpoint accepts."""
        for axis in client.get("/api/filters").json()["x_axis"]:
            r = client.get("/api/cohort/progression", params={"x_axis": axis})
            assert r.status_code == 200, f"{axis} advertised but rejected"

    def test_lift_progression_happy_path(self, client):
        body = client.get(
            "/api/cohort/lift_progression", params={"sex": "M"},
        ).json()
        assert "lifts" in body or "points" in body

    def test_lift_progression_rejects_an_unknown_x_axis(self, client):
        r = client.get(
            "/api/cohort/lift_progression", params={"x_axis": "Furlongs"},
        )
        assert r.status_code == 422

    def test_lift_progression_handles_an_ordinal_axis(self, client):
        """Career quartile and bodyweight bucket cannot be derived per lift,
        so the endpoint returns an empty response rather than inventing one.
        That is a deliberate contract, and it must not be a 500."""
        r = client.get(
            "/api/cohort/lift_progression",
            params={"x_axis": "Career quartile"},
        )
        assert r.status_code == 200


class TestLifters:
    def test_search_finds_a_fixture_lifter(self, client):
        body = client.get("/api/lifters/search", params={"q": "Alice"}).json()
        assert any(row["Name"] == "Alice A" for row in body)

    def test_search_truncates_rather_than_rejecting_an_overlong_query(self, client):
        """The 50-char cap is a DoS guard, applied by truncation.

        `search_lifters` does `q.lower().strip()[:50]`, so an absurd query
        is answered cheaply instead of erroring. Asserting the truncation
        rather than a status code, because the status code alone would not
        show that the cap is doing anything.
        """
        r = client.get("/api/lifters/search", params={"q": "a" * 500})
        assert r.status_code == 200
        assert r.json() == []

    def test_search_rejects_a_too_short_query(self, client):
        """min_length=2 stops a single letter matching most of the table."""
        assert client.get(
            "/api/lifters/search", params={"q": "a"},
        ).status_code == 422

    def test_search_wildcards_are_escaped_not_expanded(self, client):
        """`%%%%%` must be a literal search, not a full-table scan."""
        r = client.get("/api/lifters/search", params={"q": "%%%%%"})
        assert r.status_code == 200
        assert r.json() == []

    def test_history_returns_meets_for_a_known_lifter(self, client):
        body = client.get("/api/lifters/Alice A/history").json()
        assert body["found"] is True
        assert len(body["meets"]) >= 3

    def test_history_reports_not_found_rather_than_erroring(self, client):
        body = client.get("/api/lifters/Nobody At All/history").json()
        assert body["found"] is False


class TestMeets:
    def test_returns_a_known_meet(self, client):
        body = client.get(
            "/api/meet", params={"name": "Ontario Champs", "date": "2025-06-01"},
        ).json()
        assert body["found"] is True
        assert body["groups"]

    def test_reports_not_found_for_an_unknown_meet(self, client):
        body = client.get(
            "/api/meet", params={"name": "No Such Meet", "date": "2025-06-01"},
        ).json()
        assert body["found"] is False

    def test_requires_both_name_and_date(self, client):
        assert client.get("/api/meet", params={"name": "Ontario Champs"}).status_code == 422

    def test_rejects_a_malformed_date(self, client):
        r = client.get(
            "/api/meet", params={"name": "Ontario Champs", "date": "June 2025"},
        )
        assert r.status_code == 422


class TestRankings:
    def test_happy_path_is_paginated(self, client):
        body = client.get("/api/rankings", params={"limit": 5}).json()
        assert "rows" in body
        assert body["window_start"] and body["window_end"]

    def test_unwhitelisted_metric_is_coerced_before_it_can_reach_sql(self, client):
        """The metric is interpolated into ORDER BY, so the whitelist is the
        injection boundary, not a convenience.

        `rankings.py` coerces an unknown value to the default rather than
        rejecting it. Asserting the coercion is the stronger test: a 200
        alone would not prove the injected string never reached the query,
        whereas `metric == "glp"` does.
        """
        r = client.get("/api/rankings", params={"metric": "total; DROP TABLE"})
        assert r.status_code == 200
        assert r.json()["metric"] == "glp"

    def test_rejects_a_negative_offset(self, client):
        assert client.get("/api/rankings", params={"offset": -1}).status_code == 422

    def test_percentiles_happy_path(self, client):
        assert client.get("/api/rankings/percentiles").status_code == 200


class TestAthleteProjection:
    def test_happy_path(self, client):
        body = client.get("/api/athlete/Bob B/projection").json()
        assert body["found"] is True

    def test_unknown_lifter_reports_not_found(self, client):
        body = client.get("/api/athlete/Nobody At All/projection").json()
        assert body["found"] is False

    def test_unknown_engine_falls_back_rather_than_erroring(self, client):
        r = client.get(
            "/api/athlete/Bob B/projection", params={"engine": "crystal_ball"},
        )
        assert r.status_code == 200
        assert r.json().get("engine") != "crystal_ball"

    def test_horizon_is_clamped_server_side_not_rejected(self, client):
        """The UI caps at 18 months; the server enforces it regardless of
        what a request asks for, and answers rather than erroring."""
        body = client.get(
            "/api/athlete/Bob B/projection", params={"horizon": 999},
        ).json()
        if body.get("found"):
            assert body["horizon_months"] <= 18

    def test_projection_engines_reports_per_engine_availability(self, client):
        """Drives the Simple/Advanced toggle, which only appears when
        Engine D clears its convergence gate."""
        body = client.get("/api/athlete/projection-engines").json()
        assert body["shrinkage"]["available"] is True
        assert "available" in body["mixed_effects"]
        assert "convergence_rate" in body["mixed_effects"]


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------


class TestManualTrajectory:
    def _payload(self, **over):
        base = {
            "sex": "M",
            "equipment": "Raw",
            "entries": [
                {"date": "2024-01-01", "total_kg": 500.0, "bodyweight_kg": 83.0},
                {"date": "2025-01-01", "total_kg": 520.0, "bodyweight_kg": 83.0},
            ],
        }
        base.update(over)
        return base

    def test_happy_path(self, client):
        r = client.post("/api/manual/trajectory", json=self._payload())
        assert r.status_code == 200

    def test_rejects_a_bad_sex(self, client):
        r = client.post("/api/manual/trajectory", json=self._payload(sex="X"))
        assert r.status_code == 422

    def test_rejects_an_oversized_entry_list(self, client):
        """The 200-entry cap is a DoS guard on a public POST."""
        entries = [
            {"date": "2024-01-01", "total_kg": 500.0, "bodyweight_kg": 83.0}
        ] * 500
        r = client.post("/api/manual/trajectory", json=self._payload(entries=entries))
        assert r.status_code == 422

    def test_rejects_an_absurd_weight(self, client):
        r = client.post(
            "/api/manual/trajectory",
            json=self._payload(entries=[
                {"date": "2024-01-01", "total_kg": 99999.0, "bodyweight_kg": 83.0},
            ]),
        )
        assert r.status_code == 422


class TestScoutReport:
    def test_happy_path(self, client):
        r = client.post("/api/scout/report", json={
            "meet_name": "Test Meet",
            "federation": "CPU",
            "location": "Guelph, ON",
            "meet_date": "2026-06-14",
            "generator_name": "",
            "generator_brand": "",
            "roster": [{"name": "Bob B", "is_homie": False}],
        })
        assert r.status_code == 200
        assert r.json()["request"]["meet_name"] == "Test Meet"

    def test_rejects_an_empty_roster(self, client):
        r = client.post("/api/scout/report", json={
            "meet_name": "Test Meet",
            "meet_date": "2026-06-14",
            "roster": [],
        })
        assert r.status_code == 422

    def test_rejects_a_malformed_meet_date(self, client):
        r = client.post("/api/scout/report", json={
            "meet_name": "Test Meet",
            "meet_date": "next June",
            "roster": [{"name": "Bob B", "is_homie": False}],
        })
        assert r.status_code == 422
