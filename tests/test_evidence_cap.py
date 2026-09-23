from __future__ import annotations

import repomind.test_impact as test_impact_module
from repomind.test_impact import TestImpactLimits as ImpactLimits


def test_evidence_candidate_budget_bounds_retention_and_preserves_priority() -> None:
    limits = ImpactLimits(
        max_evidence_candidates=1,
        max_evidence_candidates_scanned=50,
    )
    budget = test_impact_module._AnalysisBudget.start(limits)
    store = test_impact_module._EvidenceStore.start(limits, budget)
    test_path = "tests/test_target.py"
    max_retained = 0

    for index in range(39):
        assert store.consider(
            test_path,
            {
                "kind": "filename-match",
                "path": test_path,
                "target": f"app/module_{index:02d}.py",
            },
        )
        max_retained = max(max_retained, len(store.rows))

    higher_priority = {
        "kind": "dependency",
        "path": test_path,
        "target": "app/late_priority.py",
        "relationship": "import",
        "source": "import",
    }
    assert store.consider(test_path, higher_priority)
    max_retained = max(max_retained, len(store.rows))

    assert store.scanned == 40
    assert store.per_test_scanned[test_path] == 40
    assert max_retained == 1
    assert len(store.rows) == 1
    assert store.for_test(test_path) == [higher_priority]
    assert budget.reasons == {"max_evidence_candidates": 1}
