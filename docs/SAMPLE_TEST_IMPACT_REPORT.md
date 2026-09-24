# Sanitized Sample Test-Impact Report

This sample was generated with candidate `2.0.0b10` from the synthetic fixture at
`tests/fixtures/mixed_app`. The fixture contains a minimal payment service, API route,
frontend API call, component, and synthetic test. It contains no customer, tenant, financial,
credential, or proprietary repository data.

## Reproduce the analysis

Run these commands from a trusted RepoMind source checkout after installing its current
development environment:

```powershell
$sample = Join-Path $env:TEMP ("repomind-sample-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $sample | Out-Null
Copy-Item -Path ".\tests\fixtures\mixed_app\*" -Destination $sample -Recurse
repomind init "$sample"
repomind test-impact -C "$sample" --max-changed-files 10 --max-tests 10 --max-evidence 12 --format markdown backend/service.py frontend/src/api.ts
```

The two paths are explicit hypothetical changes; the command does not edit the fixture or run
its tests. Use `--format json` to inspect the complete machine-readable metadata described below.

## Verified report summary

The Markdown report produced the following substantive result:

### Changed files

- `backend/service.py` — indexed Python production source.
- `frontend/src/api.ts` — indexed TypeScript production source.

### Impacted areas

- High confidence: `backend/api.py`, `backend/service.py`,
  `frontend/src/Dashboard.tsx`, `frontend/src/api.ts`, and `tests/test_payment.py`.
- Medium confidence: `create_payment`, `POST /payments`, and `test_payment` through static
  call, route, and test relationships.
- Low confidence: `submitPayment` through a lexical frontend call relationship.

These confidence labels rank available static evidence. They are not calibrated probabilities
and do not prove runtime behavior.

### Existing tests and uncovered areas

- `tests/test_payment.py` was selected as structurally related to `backend/service.py` through
  call, import, and test-target evidence. Behavioral coverage remains **unknown** because no
  external coverage data was supplied.
- `frontend/src/api.ts` was reported as a potential test gap because no high- or
  medium-confidence test relationship was detected for that changed production area.

An uncovered area means RepoMind did not find strong enough evidence within the configured
budgets. It does not prove that no test exists.

### Recommended commands

```text
python -m pytest tests/test_payment.py
python -m pytest
```

RepoMind returned these commands as data with repository-relative working directory `.`. They
were not executed as part of generating this sample, and their presence does not guarantee
correctness or exhaustive coverage.

## Completeness and budget metadata

The corresponding JSON report used schema `repomind.test-impact.v1` and reported:

| Collection | Discovered | Returned | Truncated | Complete / exact-count signal |
| --- | ---: | ---: | --- | --- |
| Changed files | 2 | 2 | false | `discovery_complete=true`; `total_discovered_is_lower_bound=false` |
| Impacted areas | 9 | 9 | false | `discovery_complete=true`; `total_discovered_is_lower_bound=false` |
| Relevant tests | 1 | 1 | false | `discovery_complete=true`; `total_discovered_is_lower_bound=false` |
| Evidence for returned tests | 4 | 4 | false | `discovery_complete=true`; `total_discovered_is_lower_bound=false` |

The analysis scanned 4 evidence candidates, reported `analysis.truncated=false`, and retained all
4 evidence records for the returned test. These counts are exact for this small run because the
report explicitly marked discovery complete and did not mark them as lower bounds. In a truncated
report, or when `total_discovered_is_lower_bound=true`, the discovered count must not be presented
as an exact total.

## Interpretation limits

- Static repository evidence can miss dynamic dispatch, generated code, framework behavior,
  runtime configuration, and external services.
- Test recommendations are evidence-based starting points, not exhaustive coverage guarantees.
- High confidence does not mean a high probability of correctness.
- RepoMind is not a security scanner or security certification.
- A developer must review the source, evidence, gaps, metadata, and commands before acting.
