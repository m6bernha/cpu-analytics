"""
Fédération Québécoise de Dynamophilie provincial qualifying-total scraper.

FQD publishes standards via a React SPA at ``fqd-quebec.com/standards``.
The frontend is entirely client-rendered (static fetch returns a 500-byte
stub) but the SPA calls a JSON API backend at
``https://sheltered-inlet-15640.herokuapp.com/api/v1/standards`` which
returns the entire dataset (928 records covering Nationals + Provincials
x Powerlifting + Bench x Classic + Equipped x Men + Women). Scraping
that API directly avoids the Playwright runtime dependency the audit
initially recommended.

API field mapping:
  * ``level``:    ``'nats'`` -> Nationals, ``'provs'`` -> Provincials
  * ``type``:     ``'pl'``   -> SBD (3-lift), ``'bp'`` -> B (bench)
  * ``division``: ``'cl'``   -> Classic,    ``'eq'`` -> Equipped
  * ``gender``:   ``'m'`` / ``'w'``
  * ``wc``:       ``'-83 kg'`` / ``'120+ kg'`` -> ``'83'`` / ``'120+'``
  * ``ac``:       already Open / Sub-Junior / Junior / Master 1-4
  * ``total``:    QT in kg

The FQD API response does not carry an effective year, so the scraper
emits rows with the configured year (default 2026 -- the year the
scraper was written against). If FQD revises their standards the API
payload changes and the orchestrator's diff picks it up; a human
should then update ``DEFAULT_EFFECTIVE_YEAR`` to bind the new data to
the correct year.

Nationals rows from this API are ignored. The CPU scraper already
covers Nationals globally, and we don't want two sources writing into
the same key. Only ``level='provs'`` rows flow to our CSV.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import requests

log = logging.getLogger(__name__)

FQD_LANDING_URL = "https://www.fqd-quebec.com/standards"
FQD_API_URL = "https://sheltered-inlet-15640.herokuapp.com/api/v1/standards"
_USER_AGENT = "cpu-analytics-scraper/1.0 (+contact matthias.bernhard7@gmail.com)"
_HTTP_TIMEOUT = 30.0

# The API does not report an effective year. Bind the scraped data to
# this year unless a caller overrides. Bump it when FQD publishes a
# revision confirmed against the CPU calendar.
DEFAULT_EFFECTIVE_YEAR = 2026

# weight-class canonicalisation: "-83 kg" -> "83", "120+ kg" -> "120+"
_WC_RE = re.compile(r"^\s*-?\s*(\d+\+?)\s*kg\s*$", re.IGNORECASE)

_TYPE_TO_EVENT = {"pl": "SBD", "bp": "B"}
_DIVISION_TO_EQUIPMENT = {"cl": "Classic", "eq": "Equipped"}
_GENDER_TO_SEX = {"m": "M", "w": "F"}


def fetch_api_json(api_url: str = FQD_API_URL) -> list[dict]:
    """Fetch the FQD standards JSON payload."""
    r = requests.get(
        api_url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        raise RuntimeError(
            f"unexpected FQD API payload shape at {api_url}: "
            f"type={type(data).__name__}, len="
            f"{len(data) if hasattr(data, '__len__') else 'n/a'}"
        )
    return data


def download_api_snapshot(target_dir: Path, api_url: str = FQD_API_URL) -> Path:
    """Download the API JSON payload to disk so tests have a committable
    fixture and the orchestrator has a reproducible artefact."""
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / "fqd_standards.json"
    r = requests.get(
        api_url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    dst.write_bytes(r.content)
    log.info("downloaded fqd api snapshot (%d bytes)", dst.stat().st_size)
    return dst


def _normalise_wc(raw: str) -> str | None:
    m = _WC_RE.match(raw or "")
    if m is None:
        return None
    return m.group(1)


def parse_api_payload(
    records: list[dict],
    effective_year: int = DEFAULT_EFFECTIVE_YEAR,
) -> list[dict]:
    """Convert FQD API records into the common scraper row shape.

    Only ``level='provs'`` records are emitted; Nationals rows are
    dropped because the CPU scraper already owns that slice globally.
    Both Classic + Equipped and both SBD + Bench are emitted; the
    orchestrator's ``filter_in_scope`` drops Equipped / Bench rows
    downstream.
    """
    out: list[dict] = []
    for d in records:
        if d.get("level") != "provs":
            continue
        event = _TYPE_TO_EVENT.get(d.get("type", ""))
        if event is None:
            continue
        equipment = _DIVISION_TO_EQUIPMENT.get(d.get("division", ""))
        if equipment is None:
            continue
        sex = _GENDER_TO_SEX.get(d.get("gender", ""))
        if sex is None:
            continue
        wc = _normalise_wc(d.get("wc", ""))
        if wc is None:
            continue
        ac = d.get("ac", "").strip()
        if not ac:
            continue
        total = d.get("total")
        if not isinstance(total, (int, float)):
            continue
        out.append({
            "sex": sex,
            "level": "Provincials",
            "region": None,
            "division": ac,
            "equipment": equipment,
            "event": event,
            "weight_class": wc,
            "qt": float(total),
            "effective_year": effective_year,
            "province": "Quebec",
        })
    log.info("parsed %d fqd rows (provincial only)", len(out))
    return out


def parse_json_file(path: Path, effective_year: int = DEFAULT_EFFECTIVE_YEAR) -> list[dict]:
    """Read a committed snapshot JSON and parse it."""
    import json
    records = json.loads(path.read_text(encoding="utf-8"))
    return parse_api_payload(records, effective_year=effective_year)


def scrape(effective_year: int = DEFAULT_EFFECTIVE_YEAR) -> list[dict]:
    """One-shot convenience: fetch the API and return parsed rows."""
    records = fetch_api_json()
    return parse_api_payload(records, effective_year=effective_year)
