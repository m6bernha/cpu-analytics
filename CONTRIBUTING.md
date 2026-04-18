# Contributing

Thanks for considering a contribution. This is a small personal project
but issues and PRs are welcome, especially if you're a Canadian lifter
with a specific view or metric you want added.

## Quick orientation

- Read the [README](README.md) for the elevator pitch.
- Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces
  fit together.
- Read [docs/DATA.md](docs/DATA.md) for where the data comes from and
  how scope is enforced.
- Read [CLAUDE.md](CLAUDE.md) if you want the dev-level lore, the known
  gotchas, and the conventions to keep.

## Getting started locally

See [README.md](README.md) for the local-dev setup. Quick summary:

```bash
# Backend
cd cpu-analytics
python -m venv .venv
.venv/Scripts/activate          # Windows
pip install -r backend/requirements.txt
python data/preprocess.py       # needs the OpenIPF CSV first
uvicorn backend.app.main:app --reload

# Frontend (second terminal)
cd cpu-analytics/frontend
npm install
npm run dev
```

## Before you push

Run both checks locally. CI will run them again on the PR, but fixing
a failure locally is faster than round-tripping to a CI run.

```bash
# Frontend: strict TypeScript + production build
cd frontend && npm run build

# Backend: pytest (158 tests)
cd cpu-analytics
.venv/Scripts/python -m pytest backend/tests/ -v
```

If the test count looks off, it means you either added tests (good) or
accidentally broke a fixture (fix).

## Commit style

`<type>: <short description>` where `type` is one of: `feat`, `fix`,
`refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

Optional scope in parens: `feat(lifter-lookup): add class-change chip`.

Body is optional but appreciated for non-trivial changes. Describe the
**why**, not the **what** (the diff already says what).

## Filing an issue

Before filing, please check:
- The live app at https://cpu-analytics.vercel.app reproduces the issue
  (vs. your local dev environment).
- A recent deploy might be the cause. Cross-reference recent commits.
- [NEXT_STEPS.md](NEXT_STEPS.md) doesn't already list it.

When filing:
- For bugs: include the URL that reproduces, the filters you had set,
  and what you expected vs. what happened.
- For feature requests: include the lifter-facing question it answers.
  "Add a chart of X" is harder to evaluate than "I want to know Y and
  can't find it today".

## Pull request checklist

- [ ] Local `npm run build` passes.
- [ ] Local `pytest backend/tests/` passes.
- [ ] New behavior has a test if it's testable.
- [ ] No hardcoded secrets, no committed data files outside `data/qualifying_totals_canpl.csv`.
- [ ] If you added a URL-backed state key, registered it cleanly in
      `useUrlState` and the README/ARCHITECTURE docs.
- [ ] If you added a new API endpoint, updated `frontend/src/lib/api.ts`
      with a typed fetcher.

## Scope and non-goals

This is a single-scope app by design: Canadian lifters, IPF-sanctioned
meets. PRs that silently widen the scope will be asked to guard the
change behind a feature flag or a separate deploy. The scope
restriction is a product decision, not a limitation.

Non-goals (not planned, please discuss in an issue before coding):

- Hard-coded individual-lifter personalization. The app is generic.
- Support for non-IPF federations. Different federations have different
  QT standards, division conventions, and equipment categories.
- A mobile app. The responsive web app is the product.

## Code of conduct

Be respectful, be honest, assume good intent, credit your sources.

## License

By contributing, you agree your contributions are licensed under the
same [MIT license](LICENSE) as the rest of the project.
