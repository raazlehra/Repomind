**Retrieval Failure Analysis (preliminary)**

This document summarizes observed weaknesses discovered during weighted evaluation runs on deterministic fixtures.

1) Under-retrieval (initial)
- Cause: Some tiny fixtures initially lacked backend files; evaluator selected only frontend files. Fix: add backend files. Status: fixed for `realistic_c_fullstack` by adding backend/services.py, backend/models.py, backend/routes.py.

2) Budget-insensitive selection
- Observation: For `realistic_c_fullstack` at budget 500 the retriever included primary files but not `backend/routes.py` until budget reached ~1000. This is expected when budget is tight; not a bug unless critical files are omitted at high budgets.

3) Noise introduction at larger budgets
- Observation: When budgets grow, non-critical files (e.g., `backend/auth.py`) may be included, increasing `noise_ratio` to ~0.166. This reduces composite retrieval_quality in the current scoring.
- Impact: agent may receive slightly more context; severity: medium.

4) Retrieval_quality scoring
- The composite score formula (critical_recall - 0.5*secondary - 0.5*test - noise_ratio) can be negative even when critical recall is 1.0 if noise_ratio is present. This highlights the need to tune weights or add additional penalties for irrelevant files.

5) Incremental indexing
- Tests show incremental indexer updates dependencies correctly for file edits, deletions, and renames. No stale edges observed in tests.

6) Recommendations
- Improve ranking to prefer files that are part of strongly connected dependency chains of primary files; discourage including unrelated auth files unless evidence supports strong relevance.
- Add gold-standards for more fixtures and CI checks to detect regressions.
