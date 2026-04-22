"""
CPU qualifying-total scrapers.

Each submodule handles one federation (federal CPU, or a provincial body)
and exposes a parse function that returns a list of dicts matching the
schema in ``base.CSV_FIELDS``. The orchestrator in ``data/scrape_qt.py``
wires them together, validates, diffs, and writes ``qt_current.csv``.
"""
