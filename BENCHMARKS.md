# RepoMind benchmarks

RepoMind's benchmark framework measures retrieval efficiency; it does not estimate OpenAI/Codex credits, account limits, billing, or universal token savings.

## Methodology

Run:

```bash
python -m benchmarks.run_benchmark --format markdown
python -m benchmarks.run_benchmark --format json --output benchmark.json
```

The harness copies synthetic repositories from `tests/fixtures` into temporary directories. For each fixture it:

1. creates a fresh index;
2. changes one indexed source file;
3. runs incremental refresh and records how many files were parsed, reused, added, or deleted;
4. validates deterministic repository memory and records memory counts/timing;
5. retrieves Level 1 Markdown context with a 2,000 approximate-token budget;
6. compares selected files with hand-authored expected relevant files in `benchmarks/tasks.json`.

Metrics:

- **Files inspected**: ranked file records included in the task context package. This is not a claim that source files were opened.
- **Candidate files considered**: indexed file records scored for the task before budgeted selection.
- **Source context bytes retrieved**: bytes of actual source snippets emitted. Level 1 emits no source snippets, so this is zero in the run below.
- **Selected files total bytes**: combined working-tree size of selected files, reported as scale context only; those bytes were not emitted.
- **Output bytes / approximate tokens**: size of rendered RepoMind context and the local tokenizer-independent approximation.
- **File/context reduction**: provider-neutral percentage reductions derived from indexed file count and repository text bytes versus returned files and rendered context bytes. These are measurements, not credit-savings claims.
- **Retrieval latency**: ranking, package building, budget fitting, and rendering, excluding initial indexing.
- **Index size**: SQLite database plus active WAL/SHM files at measurement time.
- **Initial/incremental indexing duration**: wall-clock duration measured by `perf_counter`.
- **Memory facts / validation duration**: deterministic repository memory facts stored locally and the time spent checking whether automatic evidence still proves them.
- **Memory records**: evidence-backed memory records included in the task ContextPack after relevance filtering and caps.
- **Expected-file recall**: expected relevant files present anywhere in the returned relevant-file list divided by expected files. Expected sets are fixture-specific judgments, not ground truth for arbitrary projects.

Timing results on tiny fixtures are sensitive to machine load, filesystem caching, Python version, and fixture scale. The harness reports raw measurements so runs can be compared; it does not transform them into marketing claims.

## Measured run

Measured at: 2026-08-18T16:17:08.410676+00:00  
Python: 3.13.14  
Platform: Linux 6.1.158+, x86_64, glibc 2.41  
Context budget: 2,000 approximate tokens

### Repository indexing

| Fixture | Files | Initial (s) | Incremental (s) | Parsed incrementally | Index bytes |
|---|---:|---:|---:|---:|---:|
| mixed_app | 10 | 0.012610 | 0.006721 | 1 | 126,976 |
| python_app | 7 | 0.010889 | 0.007562 | 1 | 126,976 |

### Task retrieval

| Task | Files inspected | Source context bytes | Selected files total bytes | Output bytes | Approx. tokens | Latency (s) | Expected recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| Fix authentication refresh token bug | 5 | 0 | 1,429 | 2,516 | 627 | 0.001324 | 1.000 |
| Modify API payment validation | 6 | 0 | 986 | 3,117 | 777 | 0.001003 | 1.000 |
| Change dashboard payment component | 6 | 0 | 986 | 3,084 | 768 | 0.000825 | 1.000 |
| Update database payment model | 6 | 0 | 986 | 3,075 | 766 | 0.000831 | 1.000 |
| Locate tests for payment service | 6 | 0 | 986 | 3,093 | 771 | 0.000805 | 1.000 |

Summary for this run only:

- 5 tasks
- 12/12 expected fixture files retrieved
- mean expected-file recall: 1.000
- median retrieval latency: 0.000831 seconds
- mean approximate context size: 741.8 tokens

These perfect tiny-fixture recall values should not be extrapolated to production repositories. Broader fixture diversity and real-project, task-labeled evaluation are known future benchmark work.
