# Real Project Validation

Final verdict: **V1 RELEASE READY**

## Project

- Target: Starlette real repository copy from `C:/Users/raazl/OneDrive/Documents/Repomind/benchmarks/real_repos/starlette`
- Validation workspace: `C:\Users\raazl\AppData\Local\Temp\repomind_real_validation_starlette`
- Total files: 140
- Indexed files: 111
- Excluded / unsupported / ignored files: 29
- Index size: 1732608 bytes
- Initial indexing duration: 3.333 seconds
- Git available: None

## Architecture

- language: Python (*.py)

Detected languages:

- config: 10
- documentation: 30
- python: 71

## Repository Map Review

- Map entries at depth 3 with symbols: 111
- Python parser failures: 0
- Observation: the map represented Starlette package modules, middleware, tests, docs/config, and common exported classes/functions. No generated directories appeared in the map.
- Limitation: fixture and docs modules are intentionally numerous, so depth-limited map review remains a navigation aid rather than a complete architecture proof.

## Retrieval Results

| Task | Selected Files | Approx Tokens | Latency ms | Coverage | Missed Critical | Irrelevant |
| --- | --- | ---: | ---: | --- | --- | ---: |
| Bug fix | tests/test_testclient.py, tests/test_websockets.py, starlette/testclient.py, starlette/websockets.py, tests/middleware/test_base.py | 984 | 702.1 | 3/3 | none | 0 |
| Small feature | starlette/datastructures.py, starlette/responses.py, tests/middleware/test_base.py, tests/middleware/test_gzip.py, tests/test_applications.py | 983 | 853.7 | 1/2 | tests/test_responses.py | 0 |
| API change | starlette/routing.py, tests/test_routing.py, starlette/testclient.py, tests/test_testclient.py, starlette/applications.py | 973 | 903.4 | 2/2 | none | 0 |
| Model/data change | starlette/datastructures.py, tests/test_datastructures.py, starlette/middleware/sessions.py, starlette/_exception_handler.py, starlette/applications.py | 986 | 2136.0 | 2/2 | none | 0 |
| Test-related change | starlette/background.py, tests/middleware/test_base.py, tests/test_responses.py, tests/middleware/test_gzip.py, tests/test_background.py | 998 | 733.1 | 3/4 | starlette/responses.py | 0 |
| Configuration/build change | pyproject.toml, starlette/datastructures.py, starlette/middleware/sessions.py, .github/FUNDING.yml, .github/ISSUE_TEMPLATE/config.yml | 875 | 900.0 | 1/1 | none | 4 |
| Cross-layer change | tests/middleware/test_cors.py, tests/middleware/test_base.py, tests/middleware/test_body_limit.py, starlette/middleware/cors.py, tests/test_routing.py | 984 | 723.4 | 2/2 | none | 0 |

Classification details:

### Bug fix: fix WebSocket disconnect handling in TestClient receive loop
- CRITICAL: `tests/test_testclient.py`
- CRITICAL: `tests/test_websockets.py`
- CRITICAL: `starlette/testclient.py`
- RELEVANT: `starlette/websockets.py`
- RELEVANT: `tests/middleware/test_base.py`

### Small feature: add support for custom response header on FileResponse
- RELEVANT: `starlette/datastructures.py`
- CRITICAL: `starlette/responses.py`
- RELEVANT: `tests/middleware/test_base.py`
- RELEVANT: `tests/middleware/test_gzip.py`
- RELEVANT: `tests/test_applications.py`
- Missed critical: `tests/test_responses.py`

### API change: change Router mount path matching behavior for trailing slash redirects
- CRITICAL: `starlette/routing.py`
- CRITICAL: `tests/test_routing.py`
- RELEVANT: `starlette/testclient.py`
- RELEVANT: `tests/test_testclient.py`
- RELEVANT: `starlette/applications.py`

### Model/data change: update URLPath query parameter handling to preserve repeated values
- CRITICAL: `starlette/datastructures.py`
- CRITICAL: `tests/test_datastructures.py`
- RELEVANT: `starlette/middleware/sessions.py`
- RELEVANT: `starlette/_exception_handler.py`
- RELEVANT: `starlette/applications.py`

### Test-related change: add regression test for BackgroundTask execution after streaming response
- CRITICAL: `starlette/background.py`
- RELEVANT: `tests/middleware/test_base.py`
- CRITICAL: `tests/test_responses.py`
- RELEVANT: `tests/middleware/test_gzip.py`
- CRITICAL: `tests/test_background.py`
- Missed critical: `starlette/responses.py`

### Configuration/build change: update pyproject optional dependencies for full install extra
- CRITICAL: `pyproject.toml`
- IRRELEVANT: `starlette/datastructures.py`
- IRRELEVANT: `starlette/middleware/sessions.py`
- IRRELEVANT: `.github/FUNDING.yml`
- IRRELEVANT: `.github/ISSUE_TEMPLATE/config.yml`

### Cross-layer change: change CORS middleware preflight response headers and update tests
- CRITICAL: `tests/middleware/test_cors.py`
- RELEVANT: `tests/middleware/test_base.py`
- RELEVANT: `tests/middleware/test_body_limit.py`
- CRITICAL: `starlette/middleware/cors.py`
- OPTIONAL: `tests/test_routing.py`

## Progressive Disclosure

- Bug fix: symbol matches=1, dependencies=60, callers=3, impact direct=25, snippets=1. Decision: enough for targeted source inspection
- Model/data change: symbol matches=1, dependencies=50, callers=4, impact direct=27, snippets=1. Decision: enough for targeted source inspection
- Cross-layer change: symbol matches=1, dependencies=87, callers=0, impact direct=2, snippets=1. Decision: enough for targeted source inspection

## MCP Validation

- status: {'ok': True, 'latency_ms': 713.1239000000278}
- context: {'files': ['tests/middleware/test_cors.py', 'tests/middleware/test_base.py', 'tests/middleware/test_body_limit.py', 'starlette/middleware/cors.py', 'tests/test_routing.py'], 'latency_ms': 117.85179999969841}
- symbol: {'matches': 1, 'latency_ms': 17.181399999572022}
- callers: {'count': 0, 'latency_ms': 15.50150000002759}
- dependencies: {'count': 13, 'latency_ms': 18.499299999348295}
- impact: {'direct': 2, 'latency_ms': 17.70360000045912}
- snippets: {'count': 1, 'latency_ms': 17.239499999959662}
- refresh: {'parsed': 0, 'latency_ms': 1270.3943999995317}
- map: {'files': 82, 'latency_ms': 16.405999999733467}

CLI/MCP semantic equivalence:

- context_files_match: True
- symbol_core_match: True
- dependencies_match: True
- impact_direct_match: True

Latency comparison:

- mcp_context: 117.9 ms
- cli_context: 713.1 ms
- mcp_symbol: 17.2 ms
- cli_symbol: 597.0 ms
- mcp_dependencies: 18.5 ms
- cli_dependencies: 607.6 ms
- mcp_impact: 17.7 ms
- cli_impact: 602.6 ms

## Simulated Coding-Agent Sessions

| Task | RepoMind Calls | Source Files Opened | Broad Searches | Context Tokens | Manual Discoveries | Outcome |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Bug fix | 5 | 5 | 0 | 984 | 0 | complete surface identified |
| Model/data change | 5 | 5 | 0 | 986 | 0 | complete surface identified |
| Cross-layer change | 5 | 5 | 0 | 984 | 0 | complete surface identified |

## Naive Exploration Comparison

| Task | RepoMind Files | Naive Files | RepoMind Tokens | Naive Approx Tokens | Represented Reduction |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bug fix | 5 | 103 | 984 | 232697 | 0.996 |
| Small feature | 5 | 103 | 983 | 232697 | 0.996 |
| API change | 5 | 103 | 973 | 232697 | 0.996 |
| Model/data change | 5 | 103 | 986 | 232697 | 0.996 |
| Test-related change | 5 | 103 | 998 | 232697 | 0.996 |
| Configuration/build change | 5 | 103 | 875 | 232697 | 0.996 |
| Cross-layer change | 5 | 103 | 984 | 232697 | 0.996 |

## Incremental Refresh

- created: {'created': ['starlette/_repomind_validation_tmp.py'], 'parsed': 1}
- modified: {'modified': ['starlette/_repomind_validation_tmp.py'], 'parsed': 1}
- renamed: {'renamed': [{'from': 'starlette/_repomind_validation_tmp.py', 'to': 'starlette/_repomind_validation_tmp_renamed.py'}], 'created': [], 'deleted': [], 'parsed': 0}
- deleted: {'deleted': ['starlette/_repomind_validation_tmp_renamed.py'], 'parsed': 0}
- route_modified: {'modified': ['starlette/routing.py'], 'parsed': 1}
- route_restored: {'modified': ['starlette/routing.py'], 'parsed': 1}
- stale_temp_file_removed: True
- routing_symbols_present: True
- last_refresh_parsed: 1

## Real-World Weaknesses

- P2: Level 1 retrieval selected primary implementation files but still missed exact expected companion files for some Starlette task phrasings. Impact: Agents may need a narrow test lookup after implementation-file discovery.
- P3: Static relationships do not fully explain pytest fixture wiring and framework magic. Impact: Impact results should remain advisory rather than certain.
- P3: Repository map includes many docs/tests by design, which can be visually dense at depth 3. Impact: Use task context for coding work and map for orientation.

## Bugs Fixed

- P1 retrieval precision issue fixed: common query terms and repeated noisy symbols could swamp exact configuration or implementation targets.
- P1 CamelCase framework-term issue fixed: TestClient/WebSocket queries now preserve compound tokens and avoid repeated generic test-symbol noise.
- Added regression coverage for config-file retrieval, exact path terms, and CamelCase framework terms under large test-symbol noise.

## Remaining Limitations

- Retrieval can under-select exact expected tests at level 1 for some task phrasings.
- Static analysis does not fully model framework behavior, pytest fixtures, or dynamic imports.
- Starlette has many docs/tests; map and context output should guide discovery, not replace source inspection.
- MCP latency is higher than direct service calls, but still small relative to process-based CLI invocation in this validation.

## Release Recommendation

V1 appears release-ready. Recommended next steps are packaging/release steps, not more feature development.
