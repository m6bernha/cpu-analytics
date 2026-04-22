"""
Manitoba Powerlifting Association provincial qualifying-total scraper.

MPA publishes provincial qualifying totals as a single PDF hosted on
``manitobapowerlifting.ca`` under ``/wp-content/uploads/YYYY/MM/``.
The file is linked from ``/qualifying-totals/`` under the anchor text
"MPA PROVINCIAL QUALIFYING TOTALS". The file path encodes the effective
year (``MPA-Qual-Stds-2025.pdf`` is the 2025 standard; when MPA revises
they upload ``MPA-Qual-Stds-YYYY.pdf`` with a new year).

PDF layout (2025 document, 3 pages):

    2025 Provincial Qualifying Totals*
    CLASSIC 3-LIFT
    MEN
    Weight Class SUBJR JUNIOR OPEN M1 M2 M3 M4
    53 267.5 330
    59 290 360 402.5 335 310 280 250
    ...
    CLASSIC 3-LIFT WOMEN
    Weight Class SUBJR JUNIOR OPEN M1 M2 M3 M4
    43 132.5 177.5
    ...
    EQUIPPED 3-LIFT
    MEN
    ...
    CLASSIC BENCH ONLY MEN
    ...
    EQUIPPED BENCH ONLY WOMEN
    ...

Title + sex are sometimes on the same line ("CLASSIC 3-LIFT WOMEN") and
sometimes on separate lines ("CLASSIC 3-LIFT\\nMEN"). The parser
handles both.

Only Classic 3-LIFT rows survive the orchestrator's scope filter; the
parser emits all sections so future scope changes are a one-line flip.

The 53 kg Men and 43 kg Women rows only have SUBJR + JUNIOR values
populated (no Open / Master divisions at those classes, matching CPU
convention). The parser assigns values left-to-right into column order
SUBJR, JUNIOR, OPEN, M1, M2, M3, M4.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pdfplumber
import requests

log = logging.getLogger(__name__)

MPA_LANDING_URL = "https://manitobapowerlifting.ca/qualifying-totals/"
_USER_AGENT = "cpu-analytics-scraper/1.0 (+contact matthias.bernhard7@gmail.com)"
_HTTP_TIMEOUT = 30.0

# Direct-link regex for the MPA qualifying-totals PDF. The file name
# encodes effective year; discover_pdf_url picks the highest.
_MPA_PDF_RE = re.compile(
    r'https?://manitobapowerlifting\.ca/wp-content/uploads/\d{4}/\d{2}/'
    r'MPA-Qual-Stds-(\d{4})\.pdf',
    re.IGNORECASE,
)

# Column order on every header row.
_DIVISION_COLUMNS = (
    "Sub-Junior", "Junior", "Open",
    "Master 1", "Master 2", "Master 3", "Master 4",
)

_VALID_WC_M = {"53", "59", "66", "74", "83", "93", "105", "120", "120+"}
_VALID_WC_F = {"43", "47", "52", "57", "63", "69", "76", "84", "84+"}


def discover_pdf_url(landing_url: str = MPA_LANDING_URL) -> tuple[str, int]:
    """Fetch the MPA landing page and return the current PDF URL and
    the effective year parsed from its filename.

    Raises RuntimeError if no ``MPA-Qual-Stds-YYYY.pdf`` link is found.
    """
    r = requests.get(
        landing_url,
        headers={"User-Agent": _USER_AGENT},
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    matches = list(_MPA_PDF_RE.finditer(r.text))
    if not matches:
        raise RuntimeError(
            f"no MPA-Qual-Stds PDF link found on {landing_url}; "
            f"MPA likely changed their site"
        )
    best: tuple[str, int] | None = None
    for m in matches:
        year = int(m.group(1))
        if best is None or year > best[1]:
            best = (m.group(0), year)
    assert best is not None
    return best


def download_pdf(url: str, target_dir: Path) -> Path:
    """Download the MPA PDF to ``target_dir`` and return the local path."""
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = url.rsplit("/", 1)[-1] or "mpa_qt.pdf"
    dst = target_dir / filename
    r = requests.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=_HTTP_TIMEOUT,
        stream=True,
    )
    r.raise_for_status()
    with dst.open("wb") as f:
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)
    log.info("downloaded mpa pdf (%d bytes) -> %s", dst.stat().st_size, dst)
    return dst


def _detect_section(line: str) -> tuple[str, str] | None:
    """Map a section header line to (equipment, event).

    Returns None if ``line`` isn't a section header.
    """
    up = line.upper()
    if "CLASSIC 3-LIFT" in up:
        return ("Classic", "SBD")
    if "EQUIPPED 3-LIFT" in up:
        return ("Equipped", "SBD")
    if "CLASSIC BENCH ONLY" in up:
        return ("Classic", "B")
    if "EQUIPPED BENCH ONLY" in up:
        return ("Equipped", "B")
    return None


def _detect_sex(line: str) -> str | None:
    """Detect an M/F marker on a header line.

    Returns "M" / "F" / None. Matches either a bare ``MEN`` / ``WOMEN``
    line or a section line with the sex concatenated (``CLASSIC 3-LIFT
    WOMEN``).
    """
    up = line.upper().rstrip()
    if up == "MEN" or up.endswith(" MEN"):
        return "M"
    if up == "WOMEN" or up.endswith(" WOMEN"):
        return "F"
    return None


def _parse_data_row(line: str, sex: str) -> tuple[str, list[float]] | None:
    """If ``line`` begins with a valid weight class, return
    ``(weight_class, qt_values_in_column_order)``. Otherwise None.
    """
    tokens = line.split()
    if not tokens:
        return None
    wc = tokens[0]
    valid = _VALID_WC_M if sex == "M" else _VALID_WC_F
    if wc not in valid:
        return None
    values: list[float] = []
    for t in tokens[1:]:
        try:
            values.append(float(t))
        except ValueError:
            return None
    return wc, values


def parse_pdf(pdf_path: Path) -> list[dict]:
    """Parse the MPA PDF into QT rows.

    Emits every section (Classic 3-LIFT, Equipped 3-LIFT, Classic Bench
    Only, Equipped Bench Only). The orchestrator drops Equipped and
    Bench rows via ``filter_in_scope``.
    """
    rows: list[dict] = []
    effective_year: int | None = None

    with pdfplumber.open(pdf_path) as pdf:
        all_text = "\n".join(
            (page.extract_text() or "") for page in pdf.pages
        )

    # Year of standard is in the title line e.g.
    # "2025 Provincial Qualifying Totals*"
    year_m = re.search(r"(20\d{2})\s+Provincial\s+Qualifying", all_text)
    if year_m is not None:
        effective_year = int(year_m.group(1))
    else:
        # Fall back: parser must emit a year, use a conservative default
        # if the title text changed.
        raise RuntimeError(
            "could not find 'YYYY Provincial Qualifying' title in MPA PDF"
        )

    current_equipment: str | None = None
    current_event: str | None = None
    current_sex: str | None = None
    in_data_block = False

    for raw in all_text.splitlines():
        line = raw.strip()
        if not line:
            continue

        # Section header (may or may not include the sex marker).
        section = _detect_section(line)
        if section is not None:
            current_equipment, current_event = section
            current_sex = _detect_sex(line)
            in_data_block = False
            continue

        # Sex marker on its own line.
        sex = _detect_sex(line)
        if sex is not None and current_equipment is not None:
            current_sex = sex
            in_data_block = False
            continue

        # Column header -- enter data block.
        if line.lower().startswith("weight class"):
            in_data_block = True
            continue

        if not in_data_block or current_sex is None:
            continue
        if current_equipment is None or current_event is None:
            continue

        parsed = _parse_data_row(line, current_sex)
        if parsed is None:
            continue
        wc, values = parsed

        # Map values left-to-right into the canonical column order.
        # Rows with only 2 values (53 kg M, 43 kg F) populate
        # Sub-Junior + Junior only.
        for i, qt in enumerate(values):
            if i >= len(_DIVISION_COLUMNS):
                break
            division = _DIVISION_COLUMNS[i]
            rows.append({
                "sex": current_sex,
                "level": "Provincials",
                "region": None,
                "division": division,
                "equipment": current_equipment,
                "event": current_event,
                "weight_class": wc,
                "qt": float(qt),
                "effective_year": effective_year,
                "province": "Manitoba",
            })

    log.info("parsed %d rows from MPA pdf", len(rows))
    return rows
