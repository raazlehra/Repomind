from __future__ import annotations

import json
from pathlib import Path

from tools.evaluate_real_repos import load_spec, render_markdown, run_validation


def test_real_world_validation_outputs_sanitized_json(python_repo: Path, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "repository_id": "anon-python-app",
                "repository": str(python_repo),
                "language_framework": "Python test fixture",
                "budget": 1200,
                "level": 1,
                "tasks": [
                    {
                        "query": "fix authentication login route",
                        "expected_files": [
                            "app/auth.py",
                            "app/routes.py",
                            "tests/test_auth.py",
                        ],
                        "notes": "expected chosen before run",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_validation(load_spec(spec_path))

    assert result["privacy"] == {
        "source_code_stored": False,
        "secrets_stored": False,
        "automatic_upload": False,
        "token_counts_are_estimates": True,
        "provider_credit_savings_claimed": False,
    }
    assert result["repository"]["repository_id"] == "anon-python-app"
    assert result["repository"]["language_framework"] == "Python test fixture"
    assert result["repository"]["repomind_version"] == "2.0.0b10"
    assert result["repository"]["indexed_file_count"] > 0
    assert result["repository"]["indexed_text_bytes"] > 0
    assert result["repository"]["approximate_repository_tokens"] > 0
    task = result["tasks"][0]
    assert task["task_query"] == "fix authentication login route"
    assert task["expected_important_files"] == [
        "app/auth.py",
        "app/routes.py",
        "tests/test_auth.py",
    ]
    assert "files_returned_by_repomind" in task
    assert "expected_file_hits" in task
    assert 0.0 <= task["expected_file_recall"] <= 1.0
    assert task["files_returned_count"] == len(task["files_returned_by_repomind"])
    assert task["approximate_context_tokens"] > 0
    assert task["approximate_repository_tokens"] == result["repository"][
        "approximate_repository_tokens"
    ]
    serialized = json.dumps(result).lower()
    assert "snippet" not in serialized
    assert "rendered" not in serialized
    assert "content" not in serialized


def test_real_world_validation_markdown_has_summary_without_snippets(
    python_repo: Path, tmp_path: Path
) -> None:
    result = run_validation(
        {
            "repository_id": "anon-python-app",
            "repository": str(python_repo),
            "language_framework": "Python",
            "tasks": [
                {
                    "query": "find email notification code",
                    "expected_files": ["app/email.py"],
                    "notes": "noisy | needs review",
                }
            ],
        }
    )

    markdown = render_markdown(result)

    assert "# RepoMind real-world validation" in markdown
    assert "This report is sanitized by design" in markdown
    assert "Approximate repository tokens" in markdown
    assert "Expected-file hits" in markdown
    assert "noisy \\| needs review" in markdown
    assert "def " not in markdown
    assert "class " not in markdown


def test_real_world_validation_rejects_missing_expected_files(tmp_path: Path) -> None:
    spec_path = tmp_path / "bad.json"
    spec_path.write_text(
        json.dumps(
            {
                "repository_id": "anon",
                "repository": str(tmp_path),
                "tasks": [{"query": "task"}],
            }
        ),
        encoding="utf-8",
    )

    try:
        load_spec(spec_path)
    except ValueError as exc:
        assert "expected_files" in str(exc)
    else:
        raise AssertionError("expected invalid spec to fail")
