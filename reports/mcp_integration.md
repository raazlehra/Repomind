# RepoMind MCP Integration Report

Final verdict: **MCP INTEGRATION READY**

## 1. MCP Architecture

RepoMind MCP is a thin adapter over existing RepoMind APIs:

Coding agent -> MCP stdio -> `repomind.mcp` -> `repomind.services` -> existing retrieval, query, index, graph, map, and refresh APIs -> SQLite index / repository.

The adapter does not shell out to `repomind context`, `repomind symbol`, or other CLI commands. Shared behavior lives in `repomind.services` so CLI and MCP can use the same core APIs without duplicating retrieval logic.

## 2. Transport Selected

Transport: standard MCP stdio.

Reason: stdio is the simplest local coding-agent transport. Agents can launch `repomind mcp` as a child process and communicate over stdin/stdout. No custom protocol, web server, or cloud service was introduced.

## 3. Tools Implemented

- `repomind_status`
- `repomind_context`
- `repomind_symbol`
- `repomind_callers`
- `repomind_dependencies`
- `repomind_impact`
- `repomind_snippets`
- `repomind_refresh`
- `repomind_map`

## 4. Installation Command

```bash
pip install -e .
repomind mcp
```

The package now depends on `mcp>=2,<3`.

## 5. Test Results

Dedicated MCP tests:

```text
python -m pytest tests\test_mcp.py -q
7 passed
```

Full test suite:

```text
python -m pytest -q
48 passed
```

## 6. CLI/MCP Equivalence Results

Covered by `tests/test_mcp.py`:

- Context equivalence: MCP `repomind_context` selected files match CLI `repomind context` for the same repository, task, budget, and level.
- Symbol equivalence: MCP symbol core fields match CLI `repomind symbol`; MCP additionally includes useful relationships.
- Dependencies equivalence: MCP `repomind_dependencies` matches CLI `repomind dependencies`.
- Impact equivalence: MCP `repomind_impact` direct dependents match CLI `repomind impact`.

Exact presentation differs because MCP returns structured content rather than CLI-rendered text.

## 7. MCP Overhead Measurement

Measured locally against `tests/fixtures/realistic_c_fullstack` for `repomind_context`, budget 1000, level 1:

- Direct service call: 18.697 ms
- In-process MCP client call: 195.845 ms
- Observed adapter/client overhead: 177.148 ms

This measures local Python SDK client/server overhead in a single run; it is not a benchmark claim. The MCP adapter does not rebuild indexes, spawn subprocesses, or rescan repositories for read-only calls.

## 8. Security Considerations

- Local-first only.
- No telemetry.
- No cloud upload.
- No external AI API calls.
- No repository source execution.
- No `eval` or `exec`.
- No MCP query tool shells out to RepoMind CLI commands.
- Every request requires an explicit repository path.
- Snippets are bounded and only read indexed symbols or indexed files under the repository.
- Normal errors return structured payloads instead of raw stack traces.

## 9. Current Supported Agent Integrations

Validated:

- Official Python MCP SDK in-process client.
- Local launch command shape: `repomind mcp`.

Not claimed as tested:

- Specific desktop IDE/agent clients.
- Remote HTTP/SSE MCP deployment.

## 10. Known Limitations

- The MCP server uses stdio only for this milestone.
- RepoMind remains static-analysis based; no embeddings, semantic/vector retrieval, cloud sync, or UI were added.
- Static call resolution remains conservative for dynamic dispatch, reflection, framework magic, and dependency injection.
- `repomind_snippets` is intentionally bounded and is not a generic filesystem reader.
- Impact results preserve RepoMind confidence labels and mark heuristic results rather than treating them as certain.
