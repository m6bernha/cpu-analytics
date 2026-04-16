"""Regression tests for DuckDB concurrency.

Before the per-request cursor fix (G1), 32 parallel threads hitting the
shared base connection would raise `_duckdb.InvalidInputException: No open
result set` because DuckDBPyConnection is not safe for concurrent
execute() calls.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from backend.app.qt import get_qt_standards, compute_blocks
from backend.app.lifters import search_lifters
from backend.app.data import get_cursor


def _run_qt_standards(_: int) -> int:
    df = get_qt_standards()
    return len(df)


def _run_qt_blocks(_: int) -> int:
    blocks = compute_blocks(country="Canada", federation="CPU")
    return sum(len(v) for v in blocks.values())


def _run_search(_: int) -> int:
    return len(search_lifters(q="Bo", country="Canada", parent_federation="IPF"))


def _run_simple_count(_: int) -> int:
    cur = get_cursor()
    row = cur.execute("SELECT COUNT(*) FROM qt_standards").fetchone()
    return int(row[0]) if row else 0


class TestConcurrency:
    def test_32_parallel_qt_standards(self, test_conn):
        with ThreadPoolExecutor(max_workers=32) as ex:
            results = list(ex.map(_run_qt_standards, range(32)))
        assert all(r > 0 for r in results)

    def test_32_parallel_qt_blocks(self, test_conn):
        with ThreadPoolExecutor(max_workers=32) as ex:
            results = list(ex.map(_run_qt_blocks, range(32)))
        # All returns non-negative. Empty result (0) is fine for synthetic data.
        assert all(r >= 0 for r in results)

    def test_32_parallel_mixed_queries(self, test_conn):
        """Most realistic: mix of different query types hitting in parallel."""
        tasks = [_run_qt_standards, _run_qt_blocks, _run_search, _run_simple_count] * 8
        with ThreadPoolExecutor(max_workers=32) as ex:
            futures = [ex.submit(t, i) for i, t in enumerate(tasks)]
            # .result() re-raises any exception from the thread
            results = [f.result(timeout=30) for f in futures]
        assert len(results) == 32

    def test_cursors_are_independent(self, test_conn):
        """Two cursors can hold open result sets simultaneously."""
        c1 = get_cursor()
        c2 = get_cursor()
        r1 = c1.execute("SELECT COUNT(*) FROM openipf")
        r2 = c2.execute("SELECT COUNT(*) FROM qt_standards")
        # Consume both
        n1 = r1.fetchone()[0]
        n2 = r2.fetchone()[0]
        assert n1 > 0 or n1 == 0  # synthetic data might have 0
        assert n2 > 0
