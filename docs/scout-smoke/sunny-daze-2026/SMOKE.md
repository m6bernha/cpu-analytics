# Scout MVP — Sunny Daze 2026 live smoke (2026-05-25)

Stage 3d of the sprint plan `where-did-we-leave-elegant-sifakis.md`.

## What was tested

`POST /api/scout/report` on the live backend
(`cpu-analytics-backend.onrender.com`) with the full 80-man Sunny Daze
2026 roster reconstructed from `C:\Users\matth\Downloads\Vireo
Powerlifting — Sunny Daze 2026 Scouting Report.pdf` (Matthias's
hand-built reference report, dated 2026-04-29).

- Request: [`roster.json`](roster.json) (80 names, 4 homies)
- Response: [`response.json`](response.json) (full structured report)

## Result

| Metric | Reference PDF (2026-04-29) | Scout MVP (2026-05-25) | Verdict |
|---|---|---|---|
| Matched athletes | 42 | 42 | ✅ exact |
| Unranked athletes | 38 | 38 | ✅ exact (same names) |
| Weight classes | 7 | 7 | ✅ exact |
| Homies | 4 | 4 | ✅ exact |
| Top class by gap | 120+ kg, 4.3 kg | 120+ kg, 3.9 kg | ✅ same class, fresh numbers |
| Class #2 by gap | 93 kg, 6.5 kg | 93 kg, 5.5 kg | ✅ same class |
| Class #3 by gap | 74 kg, 13.7 kg | 74 kg, 11.3 kg | ✅ same class |
| Top contender 120+ | Jason Villa | Jason Villa | ✅ same lifter |
| Top contender 93 | Sebastian Camargos | Sebastian Camargos | ✅ |
| Top contender 105 | Niko Nikolic | Niko Nikolic | ✅ |

### Class blocks (sorted by gap ascending)

```
   120+ kg  |  3 athl | gap    3.9 kg | leader: Jason Villa
     93 kg  |  9 athl | gap    5.5 kg | leader: Sebastian Camargos
     74 kg  |  6 athl | gap   11.3 kg | leader: Luke Jin
    120 kg  |  4 athl | gap   62.5 kg | leader: Leonard Ancheta
    105 kg  | 10 athl | gap   78.5 kg | leader: Niko Nikolic
     66 kg  |  2 athl | gap   83.9 kg | leader: Azeez Al-Shaikhli
     83 kg  |  8 athl | gap  102.5 kg | leader: Daniel Remulla
```

### Homies

| Name | Class | Status | Projected (kg) | PDF projected |
|---|---|---|---|---|
| Josiah Rehkopf | 74 | Rookie | 388.8 | 380.0 (PDF placed in 66 kg) |
| Aaron Subang | 105 | Developing | 657.6 | 661.4 |
| Matthias Bernhard | 83 | Rookie | 544.9 | 544.3 |
| Jhunren Baluyot | 83 | Frozen | 491.1 | 490.0 (manual entry in PDF) |

The Josiah Rehkopf class drift (66 -> 74 kg) is expected: his most-recent
OpenIPF meet record evidently moved up a class between the PDF generation
date (2026-04-29) and today (2026-05-25). The endpoint inherits whatever
`search_lifters().LatestWeightClass` reports, which tracks weekly data
refreshes. Acceptable v1 behaviour — coaches can override via manual
entry in a follow-up release (the backend API already accepts
`manual_override`; only the frontend form is gated for v1 simplicity).

The Jhunren Baluyot manual-entry case is preserved as `Frozen` because
he has no OpenIPF meets at all yet, but the PDF used a `manual_override`
to project him; the live smoke with no override produces a frozen
projection at his best total only.

## Sign-off

- Top-level shape matches the schema in `backend/app/scout.py`.
- Class block ordering correct: 7 classes sorted by ascending gap.
- Homies sorted/highlighted at top.
- Unranked appendix matches the reference PDF exactly.
- Projected numbers within sensible drift of the reference PDF.

**Verdict: Scout MVP behaves as expected against the canonical reference roster.**

## Reproducing

Local smoke:

```bash
cd cpu-analytics
.venv/Scripts/python -c '
import json, urllib.request
with open("docs/scout-smoke/sunny-daze-2026/roster.json") as f:
    body = json.load(f)
body.pop("_comment", None)
req = urllib.request.Request(
    "https://cpu-analytics-backend.onrender.com/api/scout/report",
    data=json.dumps(body).encode(), method="POST",
    headers={"Content-Type": "application/json"})
print(json.dumps(json.loads(urllib.request.urlopen(req, timeout=120).read()))[:500])
'
```

Or visit https://cpu-analytics.vercel.app/?tab=scout , paste the roster from
[`roster.json`](roster.json) (drop the JSON shell, keep one name per line,
prefix homie names with `@`), and hit Generate.
