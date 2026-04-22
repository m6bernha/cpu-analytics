"""IPF GL Points (Goodlift coefficient) for Raw SBD.

IPF GL Points is the IPF's replacement for the retired 2019 IPF Points
formula. It normalizes across bodyweight and sex so totals are comparable
regardless of weight class. Elite scores land around 100-120.

Formula: GLP = 100 * TotalKg / (A - B * exp(-C * BW))

Coefficients are sex-specific for Raw SBD (Classic). Equipped and
single-lift coefficients exist but are out of scope for v1.

Age is accepted in the signature for forward compatibility with a
possible Masters adjustment layer, but the base IPF GL formula does
not apply an age factor -- Masters GLP uses the same coefficients as
Open. If/when age-adjusted points ship, they will be an additive
multiplier on top of this base, not a change to the coefficients.
"""

from __future__ import annotations

import math


# Raw Classic SBD coefficients, published by the IPF.
_RAW_SBD_COEFFS: dict[str, tuple[float, float, float]] = {
    "M": (1199.72839, 1025.18162, 0.00921025),
    "F": (610.32796, 1045.59282, 0.03048),
}


def ipf_gl_points(
    total_kg: float | None,
    bw_kg: float | None,
    age: float | None,  # noqa: ARG001 -- reserved for future Masters adjustment
    sex: str | None,
) -> float | None:
    """Return IPF GL Points for a Raw SBD total, or None on invalid input.

    Invalid input covers: null, zero-or-negative total/bw, unknown sex,
    or a computed denominator <= 0 (which would indicate pathological
    coefficients, not real lifter data).
    """
    if total_kg is None or bw_kg is None or sex is None:
        return None
    if total_kg <= 0 or bw_kg <= 0:
        return None
    key = sex.strip().upper()
    coeffs = _RAW_SBD_COEFFS.get(key)
    if coeffs is None:
        return None
    a, b, c = coeffs
    denom = a - b * math.exp(-c * float(bw_kg))
    if denom <= 0:
        return None
    return 100.0 * float(total_kg) / denom


# Bracket boundaries from the Sean Yen pivot: narrower steps at higher
# strength to catch plateau resolution where it matters most.
GLP_BRACKET_EDGES: tuple[float, ...] = (60, 70, 80, 90, 95, 100, 105, 110, 115, 120)

GLP_BRACKET_LABELS: tuple[str, ...] = (
    "<60", "60-70", "70-80", "80-90", "90-95", "95-100",
    "100-105", "105-110", "110-115", "115-120", ">=120",
)


def assign_glp_bracket(glp: float | None) -> str:
    """Return the bracket label containing glp, or '<60' for null / non-positive.

    Lower boundary is inclusive, upper boundary is exclusive, except the
    topmost bracket which captures everything >=120.
    """
    if glp is None or glp <= 0 or math.isnan(glp) or math.isinf(glp):
        return GLP_BRACKET_LABELS[0]
    for i, edge in enumerate(GLP_BRACKET_EDGES):
        if glp < edge:
            return GLP_BRACKET_LABELS[i]
    return GLP_BRACKET_LABELS[-1]
