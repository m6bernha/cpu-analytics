"""Unit tests for the per-IP sliding-window rate limiter.

Built against a dedicated FastAPI app so the limiter runs enabled without
interfering with the shared TestClient suites, which disable it globally
via RATE_LIMIT_ENABLED=0 in conftest.py.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.rate_limit import RateLimitMiddleware


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _make_app(clock, limit=3, window=60.0):
    app = FastAPI()

    @app.post("/limited")
    def limited():
        return {"ok": True}

    @app.post("/open")
    def open_():
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware,
        rules={("POST", "/limited"): (limit, window)},
        enabled=True,
        clock=clock,
    )
    return app


class TestRateLimitMiddleware:
    def test_allows_up_to_limit_then_429(self):
        client = TestClient(_make_app(FakeClock()))
        for _ in range(3):
            assert client.post("/limited").status_code == 200
        resp = client.post("/limited")
        assert resp.status_code == 429
        assert resp.json()["error"] == "rate_limited"
        assert "Retry-After" in resp.headers

    def test_window_expiry_resets_budget(self):
        clock = FakeClock()
        client = TestClient(_make_app(clock))
        for _ in range(3):
            assert client.post("/limited").status_code == 200
        assert client.post("/limited").status_code == 429
        clock.t += 61.0
        assert client.post("/limited").status_code == 200

    def test_unmatched_route_never_limited(self):
        client = TestClient(_make_app(FakeClock()))
        for _ in range(10):
            assert client.post("/open").status_code == 200

    def test_disabled_flag_bypasses(self):
        app = FastAPI()

        @app.post("/limited")
        def limited():
            return {"ok": True}

        app.add_middleware(
            RateLimitMiddleware,
            rules={("POST", "/limited"): (1, 60.0)},
            enabled=False,
        )
        client = TestClient(app)
        for _ in range(5):
            assert client.post("/limited").status_code == 200

    def test_xff_last_entry_is_the_trusted_identity(self):
        clock = FakeClock()
        client = TestClient(_make_app(clock))
        # Spoofable first entry varies; trusted last entry stays the same,
        # so the budget is shared and exhausts.
        for _ in range(3):
            r = client.post(
                "/limited", headers={"x-forwarded-for": "1.1.1.1, 9.9.9.9"}
            )
            assert r.status_code == 200
        r = client.post(
            "/limited", headers={"x-forwarded-for": "2.2.2.2, 9.9.9.9"}
        )
        assert r.status_code == 429
        # A different trusted (last) IP gets its own budget.
        r = client.post(
            "/limited", headers={"x-forwarded-for": "1.1.1.1, 8.8.8.8"}
        )
        assert r.status_code == 200
