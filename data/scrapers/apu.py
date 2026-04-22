"""
Alberta Powerlifting Union provincial qualifying-total scraper.

APU publishes provincial qualifying standards as JPG images on
``albertapowerlifting.com/?page_id=164``. There are four images -- Men
Classic, Women Classic, Men Equipped, Women Equipped -- uploaded to
``/wp-content/uploads/YYYY/MM/`` with filenames like
``menclassic_orig.jpg``. The YYYY/MM folder rotates when APU republishes,
so the scraper rediscovers the current URLs from the landing page HTML.

Unlike every other provincial scraper in this pipeline, the APU source
is not machine-readable text. Rather than ship an OCR runtime dep
(tesseract system binary + pytesseract), this scraper uses
**hash-verified manual transcription**:

  1. Each release of APU standards is transcribed once, by hand, from
     the JPG into ``data/scrapers/apu_transcribed/<effective_year>/
     classic_<sex>.csv``. The SHA-256 of the source JPG that was
     transcribed is stored next to the CSV.
  2. The weekly scraper downloads the current JPG and hashes it.
  3. If the hash matches a known release, the scraper emits the
     committed CSV rows (no OCR drift risk).
  4. If the hash differs, the scraper raises ``UntranscribedJpgError``.
     The orchestrator logs this as a warning so the weekly workflow
     surfaces a clear "APU published new images, re-transcribe" signal
     without taking the rest of the pipeline down.

This trades recency-of-APU-updates against data integrity: APU
historically publishes once every ~2 years, so the manual-refresh tax
is ~0.5 hour every 2 years. OCR would save that but introduces
transcription errors that silently propagate into the live site.
"""
from __future__ import annotations

import csv
import hashlib
import logging
import re
from pathlib import Path

import requests

log = logging.getLogger(__name__)

APU_LANDING_URL = "https://albertapowerlifting.com/?page_id=164"
_USER_AGENT = "cpu-analytics-scraper/1.0 (+contact matthias.bernhard7@gmail.com)"
_HTTP_TIMEOUT = 30.0

# Folder holding transcribed CSVs keyed by effective year. A release
# consists of <effective_year>/classic_m.csv + classic_f.csv +
# source_hashes.csv. The hashes file locks the bytes of the JPGs the
# transcriber viewed, so a silent APU replacement cannot get mis-mapped
# to an older transcription.
TRANSCRIBED_DIR = Path(__file__).resolve().parent / "apu_transcribed"

# Image filenames APU consistently uses (names don't rotate even when
# the upload folder does). The scraper searches the landing page HTML
# for any URL ending in these names.
_IMAGE_NAMES_CLASSIC = {
    "menclassic_orig.jpg": "M",
    "womenclassic_orig.jpg": "F",
}

_IMAGE_URL_RE = re.compile(
    r'https://[^"\s>]+?/(?P<name>menclassic_orig|womenclassic_orig'
    r'|menequipped_orig|womenequipped_orig)\.jpg',
    re.IGNORECASE,
)


class UntranscribedJpgError(RuntimeError):
    """Raised when APU serves a JPG whose SHA-256 has no committed
    transcription. The orchestrator catches this and logs it."""


def discover_image_urls(
    landing_url: str = APU_LANDING_URL,
) -> dict[str, str]:
    """Return ``{filename: full_url}`` for each distinct APU standards JPG
    referenced on the landing page. Only picks the direct
    albertapowerlifting.com host (not the Jetpack ``i0.wp.com`` CDN
    variants, which have resize query params that cause hashes to
    differ from the committed canonical hash)."""
    r = requests.get(
        landing_url,
        headers={"User-Agent": _USER_AGENT},
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    out: dict[str, str] = {}
    for m in _IMAGE_URL_RE.finditer(r.text):
        url = m.group(0)
        name = m.group("name").lower() + ".jpg"
        # Prefer the direct albertapowerlifting.com URL over i0.wp.com
        # proxied copies so hashes line up with the committed fixtures.
        if "albertapowerlifting.com/wp-content/uploads/" not in url:
            continue
        if name not in out:
            out[name] = url
    if not out:
        raise RuntimeError(
            f"no APU standards JPGs found on {landing_url}; "
            f"APU likely changed their site"
        )
    return out


def download_image(url: str, target_dir: Path) -> Path:
    """Download a JPG to ``target_dir``. Preserves the image filename so
    hash verification matches the committed canonical entry."""
    target_dir.mkdir(parents=True, exist_ok=True)
    name = url.rsplit("/", 1)[-1]
    dst = target_dir / name
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
    log.info("downloaded apu %s (%d bytes)", name, dst.stat().st_size)
    return dst


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_source_hashes(release_dir: Path) -> dict[str, str]:
    """Load ``source_hashes.csv`` in ``release_dir``. Columns:
    filename,sha256."""
    hashes_path = release_dir / "source_hashes.csv"
    if not hashes_path.exists():
        return {}
    with hashes_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {row["filename"].lower(): row["sha256"].lower() for row in reader}


def _match_release_for_hashes(
    live_hashes: dict[str, str],
) -> tuple[Path, int] | None:
    """Find a transcribed release whose ``source_hashes.csv`` matches
    EVERY downloaded JPG by hash. Returns (release_dir, effective_year)
    or None if no release matches."""
    if not TRANSCRIBED_DIR.exists():
        return None
    for release_dir in sorted(TRANSCRIBED_DIR.iterdir()):
        if not release_dir.is_dir():
            continue
        if not release_dir.name.isdigit():
            continue
        committed = _load_source_hashes(release_dir)
        if not committed:
            continue
        if all(
            committed.get(name) == sha for name, sha in live_hashes.items()
        ):
            return (release_dir, int(release_dir.name))
    return None


def _load_transcribed_rows(release_dir: Path, effective_year: int) -> list[dict]:
    """Read classic_m.csv + classic_f.csv from a release dir and emit
    row dicts matching ``data.scrapers.base.CSV_FIELDS``."""
    rows: list[dict] = []
    for sex_file, sex in (("classic_m.csv", "M"), ("classic_f.csv", "F")):
        csv_path = release_dir / sex_file
        if not csv_path.exists():
            continue
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                qt = r.get("qt", "").strip()
                if not qt or qt in ("-", "—"):
                    continue
                try:
                    qt_val = float(qt)
                except ValueError:
                    continue
                rows.append({
                    "sex": sex,
                    "level": "Provincials",
                    "region": None,
                    "division": r["division"],
                    "equipment": "Classic",
                    "event": "SBD",
                    "weight_class": r["weight_class"],
                    "qt": qt_val,
                    "effective_year": effective_year,
                    "province": "Alberta",
                })
    return rows


def scrape_with_download(
    target_dir: Path,
    landing_url: str = APU_LANDING_URL,
) -> list[dict]:
    """Download current APU JPGs, hash-match against a transcribed
    release, and emit the committed rows.

    Raises ``UntranscribedJpgError`` if the live JPGs don't match any
    committed release (i.e. APU republished and transcription is stale).
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    urls = discover_image_urls(landing_url)
    # Only pull the two Classic images -- scope is Classic + SBD; Equipped
    # stays out of the manual-transcription budget.
    classic_urls = {
        name: url for name, url in urls.items()
        if name in _IMAGE_NAMES_CLASSIC
    }
    if len(classic_urls) != len(_IMAGE_NAMES_CLASSIC):
        raise RuntimeError(
            f"missing APU classic images: found {sorted(classic_urls)}"
        )
    live_hashes: dict[str, str] = {}
    for name, url in classic_urls.items():
        local = download_image(url, target_dir)
        live_hashes[name] = _sha256(local)
        log.info("apu %s sha256=%s", name, live_hashes[name])

    match = _match_release_for_hashes(live_hashes)
    if match is None:
        raise UntranscribedJpgError(
            f"APU JPGs hash {sorted(live_hashes.items())} do not match any "
            f"transcribed release under {TRANSCRIBED_DIR}; re-transcribe "
            f"the standards (see data/scrapers/apu.py docstring)"
        )
    release_dir, year = match
    rows = _load_transcribed_rows(release_dir, effective_year=year)
    log.info(
        "apu: matched release %s (%d rows)", release_dir.name, len(rows),
    )
    return rows


def load_latest_transcribed() -> list[dict]:
    """Fixture-friendly variant: emit rows from the newest transcribed
    release on disk without hitting the network."""
    if not TRANSCRIBED_DIR.exists():
        return []
    releases = sorted(
        (d for d in TRANSCRIBED_DIR.iterdir() if d.is_dir() and d.name.isdigit()),
        key=lambda d: int(d.name),
    )
    if not releases:
        return []
    latest = releases[-1]
    return _load_transcribed_rows(latest, effective_year=int(latest.name))
