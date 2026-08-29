# RepoMind Real-World Validation

This workflow collects reproducible evidence from real repositories without storing source code, secrets, or private project details.

Use it when beta testers want to measure how RepoMind performs on their own repositories and share a sanitized result.

## Safety and privacy

Do not include proprietary source code, API keys, credentials, private keys, tokens, customer data, or internal URLs in validation reports.

The validation runner records:

- anonymous repository ID;
- language/framework label;
- indexed file count;
- indexed text bytes;
- approximate repository tokens;
- RepoMind version;
- OS and Python version;
- task/query text;
- manually defined expected important files;
- files returned by RepoMind;
- expected-file hits and recall;
- approximate context tokens;
- represented-context reduction percentage;
- retrieval latency;
- memory fact counts;
- tester notes about noise.

The validation runner does not write source snippets, source contents, secrets, file hashes, environment variables, or any automatic upload. Reports remain local until a tester chooses to share them.

Token counts are provider-neutral estimates. They are not provider tokenizer counts, billing tokens, account credits, or guaranteed savings.

## Define expected files first

For each task, identify expected important files before measuring RepoMind output when possible.

Avoid modifying expected files after seeing RepoMind results. If you discover that the expected set was wrong, record that as a note and run a new validation with a new spec rather than silently editing the old result.

## Validation spec

Create a local JSON file outside the repository under test, for example `real-validation-spec.json`:

```json
{
  "repository_id": "beta-repo-001",
  "repository": "C:/path/to/your/project",
  "language_framework": "Python/FastAPI and TypeScript/React",
  "budget": 2000,
  "level": 1,
  "tasks": [
    {
      "query": "fix authentication refresh token bug",
      "expected_files": [
        "backend/routes.py",
        "backend/services.py",
        "tests/test_auth.py"
      ],
      "notes": "Expected files were selected before running RepoMind."
    }
  ]
}
```

Use an anonymous `repository_id`. The `repository` value is used locally by the runner, but you should remove or redact it before sharing a report if it contains private path details.

Expected files and returned files are repository-relative paths. Redact proprietary path segments before sharing if needed.

## Run validation

From the RepoMind checkout:

```bash
python -m tools.evaluate_real_repos --spec real-validation-spec.json --format json --output real-validation-results.json
python -m tools.evaluate_real_repos --spec real-validation-spec.json --format markdown --output real-validation-results.md
```

The runner initializes or refreshes RepoMind's local index for the target repository, retrieves task context, and writes a sanitized report.

## Review before sharing

Before attaching results to an issue or private beta report:

1. Open the JSON or Markdown output locally.
2. Confirm it contains no proprietary source code.
3. Confirm it contains no secrets, credentials, private keys, tokens, internal hostnames, or customer data.
4. Redact local user directories or proprietary path segments if needed.
5. Include the validation spec only if it is safe to share.

Share only the sanitized result unless maintainers ask for a smaller reproduction.

## Interpreting metrics

- `expected_file_recall`: expected important files returned by RepoMind divided by manually expected files.
- `files_returned_count`: count of ranked files included in the task ContextPack.
- `approximate_context_tokens`: provider-neutral estimate for the rendered context.
- `approximate_repository_tokens`: provider-neutral estimate for indexed repository text.
- `represented_context_reduction_percent`: estimated reduction from represented indexed repository text to rendered context output.
- `retrieval_latency_seconds`: local time spent building and fitting task context.
- `memory_facts_included_count`: relevant memory records included in task context.

Use these metrics for comparison and debugging. Do not present them as provider credit savings or universal performance guarantees.

## Reproducibility checklist

When sharing a result, include:

- RepoMind version;
- OS;
- Python version;
- anonymous repository ID;
- language/framework;
- approximate repository size;
- validation spec task list;
- whether expected files were chosen before measuring;
- JSON or Markdown validation output;
- notes about noisy, missing, or misleading results.

## Relationship to synthetic benchmarks

`python -m benchmarks.run_benchmark` remains the deterministic synthetic fixture benchmark.

`python -m tools.evaluate_real_repos` is the real-world validation workflow. It uses the same retrieval and ContextPack APIs but records only sanitized task-level evidence from repositories that testers control.
