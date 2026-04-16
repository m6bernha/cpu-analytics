"""Canonical weight class mapping for IPF/CPU men and women.

Ported verbatim from the original QTchanges.py:53-108 so the new app reproduces
the same coverage numbers as qt_coverage_results.csv.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd


MEN_BOUNDS = [59, 66, 74, 83, 93, 105, 120]
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
        # 53 kg class excluded: too rare in CPU to produce meaningful stats,
        # and no QT standard exists for it. Anyone below 53.5 is dropped.
        # Historical 56 kg and similar classes promote to 59.
        if base < 53.5:
            return np.nan
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


def canonical_weight_class_bulk(
    sex_series: pd.Series,
    wc_series: pd.Series,
) -> pd.Series:
    """Vectorized canonicalization. Equivalent to row-wise canonical_weight_class
    but O(n) with numpy masks instead of Python loop.

    Used by preprocess.py on ~1M-row OpenIPF exports; the row-wise apply was
    the dominant cost in the weekly GHA workflow.
    """
    sex = sex_series.astype(str).str.strip().str.upper()
    wc_str = wc_series.astype(str).str.strip()
    plus = wc_str.str.endswith("+")
    base = pd.to_numeric(wc_str.str.rstrip("+"), errors="coerce")

    # Result starts as NaN (unmappable)
    result = pd.Series([np.nan] * len(sex), index=sex.index, dtype=object)

    # --- Men ---
    is_m = sex == "M"
    # base >= 53.5 required (53 class excluded) and not nan.
    # Anyone in [53.5, 59) promotes to 59.
    m_valid = is_m & base.notna() & (base >= 53.5)
    # 120+ if plus or base > 120
    m_shw = m_valid & (plus | (base > 120))
    result[m_shw] = "120+"
    # Promote 53.5-58.x into the 59 bucket
    m_base = base.where(~(m_valid & (base < 59)), 59)
    # For each threshold b, assign "b" to rows in m_valid where result is still NaN and base <= b
    for b in MEN_BOUNDS:
        mask = m_valid & result.isna() & (m_base <= b)
        result[mask] = str(int(b))
    # Men above all thresholds but not SHW → 120+
    m_remaining = m_valid & result.isna()
    result[m_remaining] = "120+"

    # --- Women ---
    is_f = sex == "F"
    f_valid = is_f & base.notna() & (base >= 46.5)
    # 47 class: [46.5, 47.5]
    f_47 = f_valid & (base >= 46.5) & (base <= 47.5)
    result[f_47] = "47"
    # 84+ if plus or base > 84 (and not already 47)
    f_shw = f_valid & result.isna() & (plus | (base > 84))
    result[f_shw] = "84+"
    # 52-class floor: anyone between 47.5 and 52 becomes 52
    base_adj = base.where(~(f_valid & (base > 47.5) & (base < 52)), 52)
    for b in WOMEN_BOUNDS:
        if b < 52:
            continue
        mask = f_valid & result.isna() & (base_adj <= b)
        result[mask] = str(int(b))
    f_remaining = f_valid & result.isna()
    result[f_remaining] = "84+"

    return result
