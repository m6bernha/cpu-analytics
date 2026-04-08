"""Canonical weight class mapping for IPF/CPU men and women.

Ported verbatim from the original QTchanges.py:53-108 so the new app reproduces
the same coverage numbers as qt_coverage_results.csv.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd


MEN_BOUNDS = [53, 59, 66, 74, 83, 93, 105, 120]
WOMEN_BOUNDS = [47, 52, 57, 63, 69, 76, 84]


def _parse_wc_value(wc) -> Tuple[float, bool]:
    if pd.isna(wc):
        return (np.nan, False)
    s = str(wc).strip()
    plus = s.endswith("+")
    try:
        base = float(s.rstrip("+"))
    except ValueError:
        return (np.nan, plus)
    return (base, plus)


def canonical_weight_class(sex: str, wc) -> str | float:
    """Canonicalize WeightClassKg into standard M/F classes.

    Returns a string like '59', '84+', '120+' or np.nan for unmappable inputs.
    """
    base, plus = _parse_wc_value(wc)
    if np.isnan(base):
        return np.nan

    sex = str(sex).strip().upper()
    if sex not in {"M", "F"}:
        return np.nan

    if sex == "M":
        if base < 52.5:
            return np.nan
        if 52.5 <= base <= 53.5:
            return "53"
        if plus or base > 120:
            return "120+"
        if base < 59:
            base = 59
        for b in MEN_BOUNDS:
            if base <= b:
                return str(int(b))
        return "120+"

    # F
    if base < 46.5:
        return np.nan
    if 46.5 <= base <= 47.5:
        return "47"
    if plus or base > 84:
        return "84+"
    if base < 52:
        base = 52
    for b in WOMEN_BOUNDS:
        if base <= b:
            return str(int(b))
    return "84+"
