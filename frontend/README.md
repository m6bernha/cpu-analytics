# CPU Powerlifting Analytics — Frontend

## Dev setup

The backend must be running on port 8000 before starting the frontend:

```bash
# Terminal 1 — from cpu-analytics/
source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
uvicorn backend.app.main:app --reload
```

```bash
# Terminal 2 — from cpu-analytics/frontend/
npm run dev
```

Then open http://localhost:5173.

## M3 surface

M3 ships a single generic lifter name search. Type any name to search the full OpenIPF dataset. The site is fully generic — no lifter names, divisions, or personal data are hardcoded anywhere in the UI.
