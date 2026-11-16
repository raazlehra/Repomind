from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from pydantic import StrictFloat, StrictInt

from repomind import __version__, services
from repomind.test_impact import TestImpactLimits

ToolHandler = Callable[..., dict[str, Any]]


INSTRUCTIONS = """Lehraz Atlas Free (formerly RepoMind) is a local-first static-analysis discovery accelerator.
Use repomind_context at level 1 first, inspect actual source before edits, and ask
for deeper symbols, callers, dependencies, impact, or snippets only when needed."""


def create_server(debug: bool = False, *, atlas: bool = False) -> MCPServer:
    prefix = "atlas" if atlas else "repomind"
    server = MCPServer(
        name="lehraz-atlas" if atlas else "repomind",
        title="Lehraz Atlas Free",
        version=__version__,
        instructions=INSTRUCTIONS.replace("repomind_context", f"{prefix}_context"),
        debug=debug,
    )

    def safe(handler: ToolHandler, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return handler(*args, **kwargs)
        except Exception as exc:  # MCP tool boundary: convert normal failures to structured data.
            return services.error_payload(exc, debug=debug)

    @server.tool(name=f"{prefix}_status")
    def repomind_status(repository: str) -> dict[str, Any]:
        """Check whether a repository has a valid RepoMind index."""
        return safe(services.status, repository)

    @server.tool(name=f"{prefix}_context")
    def repomind_context(
        repository: str,
        task: str,
        budget: int | None = None,
        level: int = 1,
        explain: bool = False,
    ) -> dict[str, Any]:
        """Return structured task-aware context from the existing RepoMind retriever."""
        return safe(services.context, repository, task, budget, level, explain)

    @server.tool(name=f"{prefix}_symbol")
    def repomind_symbol(repository: str, symbol: str) -> dict[str, Any]:
        """Return matching symbols with file, location, signature, type, and relationships."""
        return safe(services.symbol, repository, symbol)

    @server.tool(name=f"{prefix}_callers")
    def repomind_callers(repository: str, symbol: str) -> dict[str, Any]:
        """Return resolvable incoming call relationships for a symbol."""
        return safe(services.symbol_callers, repository, symbol)

    @server.tool(name=f"{prefix}_dependencies")
    def repomind_dependencies(repository: str, target: str) -> dict[str, Any]:
        """Return outgoing structural dependencies for a file or symbol target."""
        return safe(services.structural_dependencies, repository, target)

    @server.tool(name=f"{prefix}_impact")
    def repomind_impact(repository: str, target: str) -> dict[str, Any]:
        """Estimate dependents, affected tests, routes, and UI impact for a target."""
        return safe(services.change_impact, repository, target)


    @server.tool(name=f"{prefix}_test_impact")
    def repomind_test_impact(
        repository: str,
        changed_files: list[str] | None = None,
        base: str | None = None,
        max_graph_nodes: StrictInt = 500,
        max_graph_edges: StrictInt = 2_000,
        max_impacted_areas: StrictInt = 100,
        max_tests: StrictInt = 50,
        max_commands: StrictInt = 20,
        max_evidence_per_result: StrictInt = 10,
        max_output_bytes: StrictInt = 200_000,
        max_changed_files: StrictInt = 200,
        max_path_length: StrictInt = 1_000,
        max_test_candidates_scanned: StrictInt = 5_000,
        max_migration_candidates_scanned: StrictInt = 1_000,
        max_route_candidates_scanned: StrictInt = 5_000,
        max_direct_edges_per_file: StrictInt = 500,
        max_indirect_edges_per_file: StrictInt = 500,
        max_impacted_candidates: StrictInt = 1_000,
        max_relevant_test_candidates: StrictInt = 500,
        max_evidence_candidates: StrictInt = 5_000,
        max_command_candidates: StrictInt = 100,
        max_analysis_seconds: StrictFloat | StrictInt = 10.0,
    ) -> dict[str, Any]:
        """Analyze changes and return bounded test recommendations without executing them."""
        try:
            limits = TestImpactLimits(
                max_graph_nodes=max_graph_nodes,
                max_graph_edges=max_graph_edges,
                max_impacted_areas=max_impacted_areas,
                max_tests=max_tests,
                max_commands=max_commands,
                max_evidence_per_result=max_evidence_per_result,
                max_output_bytes=max_output_bytes,
                max_changed_files=max_changed_files,
                max_path_length=max_path_length,
                max_test_candidates_scanned=max_test_candidates_scanned,
                max_migration_candidates_scanned=max_migration_candidates_scanned,
                max_route_candidates_scanned=max_route_candidates_scanned,
                max_direct_edges_per_file=max_direct_edges_per_file,
                max_indirect_edges_per_file=max_indirect_edges_per_file,
                max_impacted_candidates=max_impacted_candidates,
                max_relevant_test_candidates=max_relevant_test_candidates,
                max_evidence_candidates=max_evidence_candidates,
                max_command_candidates=max_command_candidates,
                max_analysis_seconds=max_analysis_seconds,
            )
        except ValueError as exc:
            return services.error_payload(exc, debug=debug)
        return safe(
            services.test_impact,
            repository,
            changed_files,
            base,
            limits=limits,
        )

    test_impact_tool = server._tool_manager.get_tool(f"{prefix}_test_impact")
    if test_impact_tool is not None:
        argument_model = test_impact_tool.fn_metadata.arg_model
        argument_model.model_config["extra"] = "forbid"
        argument_model.model_rebuild(force=True)
        test_impact_tool.parameters = argument_model.model_json_schema(by_alias=True)

    @server.tool(name=f"{prefix}_snippets")
    def repomind_snippets(
        repository: str,
        target: str,
        line_bound: int | None = None,
        token_bound: int | None = None,
    ) -> dict[str, Any]:
        """Return bounded source snippets for an indexed symbol or file target."""
        return safe(services.bounded_snippets, repository, target, line_bound, token_bound)

    @server.tool(name=f"{prefix}_refresh")
    def repomind_refresh(repository: str) -> dict[str, Any]:
        """Refresh changed files incrementally and return index health."""
        return safe(services.refresh, repository)

    @server.tool(name=f"{prefix}_map")
    def repomind_map(
        repository: str,
        depth: int | None = None,
        include_symbols: bool = False,
    ) -> dict[str, Any]:
        """Return the compact repository map."""
        return safe(services.repository_map, repository, depth, include_symbols)

    @server.tool(name=f"{prefix}_stats")
    def repomind_stats(repository: str) -> dict[str, Any]:
        """Return repository intelligence metrics from the current index."""
        return safe(services.stats, repository)

    @server.tool(name=f"{prefix}_memory")
    def repomind_memory(
        repository: str,
        task: str | None = None,
        category: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Return bounded repository memory, optionally filtered or relevant to a task."""
        if task:
            return safe(services.memory_for_task, repository, task, limit)
        return safe(services.memory_list, repository, category, status, limit)

    return server


def run_stdio(debug: bool = False, *, atlas: bool = False) -> None:
    create_server(debug=debug, atlas=atlas).run("stdio")


if __name__ == "__main__":
    run_stdio()
