# RepoMind V1 Release Readiness

Final verdict: **V1 READY FOR AGENT INTEGRATION**

## Quality Gate

| Check | Status | Evidence |
| --- | --- | --- |
| Test suite | PASS | `python -m pytest -q` passed: 41 tests |
| Ruff | PASS | `python -m ruff check .` passed |
| Mypy | PASS | `python -m mypy repomind` passed: 28 source files |
| Build | PASS | `python -m build` built sdist and wheel |
| Weighted retrieval benchmark | PASS | `python -m tools.evaluate_weighted` completed; JSON saved to `reports/weighted_results.json` |
| Deterministic retrieval benchmark | PASS | `python -m tools.evaluate_retrieval` completed; JSON saved to `reports/retrieval_results.json` |

## Retrieval Targets

| Fixture | Budget / level evidence | Selected files | Critical recall | Secondary recall | Test recall | Noise |
| --- | --- | --- | --- | --- | --- | --- |
| Authentication backend | 1000 tokens, level 3 | `backend/services.py`, `tests/test_auth.py`, `backend/repository.py`, `backend/models.py` | 1.0 | 1.0 | 1.0 | 0.25 |
| React frontend | 1000 tokens, level 3 | `frontend/src/components/Dashboard.tsx`, `frontend/src/api.ts` | 1.0 | 1.0 | 1.0 | 0.0 |
| Full-stack dashboard API | 1000 tokens, level 3 | `frontend/src/components/Dashboard.tsx`, `backend/routes.py`, `backend/services.py`, `frontend/src/apiClient.ts`, `backend/models.py` | 1.0 | 1.0 | 1.0 | 0.0 |
| Scale small | 1000 tokens, level 3 | `frontend/src/components/Dashboard.tsx`, `backend/routes.py`, `backend/services.py`, `frontend/src/apiClient.ts`, `backend/models.py` | 1.0 | 1.0 | 1.0 | 0.0 |
| Scale medium | 1000 tokens, level 3 | `frontend/src/components/Dashboard.tsx`, `backend/routes.py`, `backend/services.py`, `frontend/src/apiClient.ts`, `backend/models.py` | 1.0 | 1.0 | 1.0 | 0.0 |

Authentication recall is 1.0 for every evaluated budget, including 500, 1000, 2000, 5000, and 10000. The full-stack dashboard API benchmark includes the dashboard component, backend service, frontend API client, backend model/schema, and backend route. `backend/auth.py` is not selected in the normal full-stack benchmark.

## Readiness Notes

- Supported languages: Python; JavaScript, TypeScript, JSX, and TSX; shallow fallback extraction for config, documentation, shell, SQL, and text.
- Privacy guarantees: default operation is local; RepoMind stores compact structural metadata in a local SQLite cache and does not require network calls for indexing or retrieval.
- Incremental-index behavior: initial indexing builds the local cache; refresh updates changed files and rebuilds dependency graph state; watch mode can debounce file events when the optional `watchdog` dependency is installed.
- Known limitations: fallback-language extraction is intentionally shallow; static call resolution remains conservative for dynamic dispatch, reflection, runtime-generated imports, framework magic, and dependency injection; token counts are local approximations.

## Changes Verified

- Retrieval now admits high-confidence outgoing structural import dependencies from already relevant non-test files, allowing critical indirect dependencies such as `services.py -> repository.py -> models.py` without reintroducing weak incoming graph noise.
- Query aliases remain deterministic and generic. `api` maps to route terminology, including singular/plural route terms; generic `response` does not broadly promote API files by itself.
- Ruff excludes environment, build, generated, fixture, vendored benchmark, and local stub directories while preserving lint coverage for RepoMind source, tests, and tooling.
