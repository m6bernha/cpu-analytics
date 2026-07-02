"""Tests for the /api/meta/freshness endpoint and meta module."""

from __future__ import annotations

from backend.app import meta


class TestGetFreshness:
    def test_returns_latest_meet_date_and_row_count(self, test_conn):
        meta.get_freshness.cache_clear()
        out = meta.get_freshness()
        # Latest meet across the synthetic rows is Alice's 2025-06-01.
        assert out["latest_meet_date"] == "2025-06-01"
        assert out["row_count"] == 13

    def test_result_is_cached(self, test_conn):
        meta.get_freshness.cache_clear()
        first = meta.get_freshness()
        second = meta.get_freshness()
        assert first is second


class TestFreshnessEndpoint:
    def test_endpoint_returns_200_with_expected_shape(self, test_conn):
        from fastapi.testclient import TestClient

        from backend.app.main import app

        meta.get_freshness.cache_clear()
        client = TestClient(app)
        response = client.get("/api/meta/freshness")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["latest_meet_date"] == "2025-06-01"
        assert body["row_count"] == 13
