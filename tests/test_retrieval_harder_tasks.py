from __future__ import annotations

from pathlib import Path

from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.retrieval import ContextRetriever


def test_indirect_dependency_retrieval(tmp_path: Path) -> None:
    repo = Path("tests/fixtures/realistic_c_fullstack")
    idx = Indexer(repo)
    idx.initialize(force=True)

    with IndexDatabase(repo) as db:
        retriever = ContextRetriever(db)
        query = "Change dashboard API response"
        expected_primary = {
            "backend/routes.py",
            "backend/services.py",
            "backend/models.py",
            "frontend/src/apiClient.ts",
        }
        pkg = retriever.build_context(query, 2000, 3)
        selected = {f["path"] for f in pkg.get("relevant_files", [])}
        # The test documents the desired behavior: retrieval should include the
        # backend route/service/model and the frontend api client for cross-layer
        # changes to the dashboard API response.
        assert expected_primary.issubset(selected)


def test_graph_expansion_avoids_unrelated_service_neighbors(tmp_path: Path) -> None:
    repo = Path("tests/fixtures/realistic_c_fullstack")
    idx = Indexer(repo)
    idx.initialize(force=True)

    with IndexDatabase(repo) as db:
        retriever = ContextRetriever(db)
        pkg = retriever.build_context("Change dashboard API response", 10000, 3)
        selected = {f["path"] for f in pkg.get("relevant_files", [])}

    assert "backend/routes.py" in selected
    assert "backend/auth.py" not in selected


def test_auth_refresh_retrieval_includes_structural_model_dependency(tmp_path: Path) -> None:
    repo = Path("tests/fixtures/realistic_a_backend")
    idx = Indexer(repo)
    idx.initialize(force=True)

    with IndexDatabase(repo) as db:
        retriever = ContextRetriever(db)
        pkg = retriever.build_context("fix authentication refresh token", 1000, 3)
        selected = {f["path"] for f in pkg.get("relevant_files", [])}

    assert {"backend/services.py", "backend/models.py"}.issubset(selected)


def test_api_alias_promotes_route_without_broad_response_expansion(tmp_path: Path) -> None:
    repo = Path("tests/fixtures/realistic_c_fullstack")
    idx = Indexer(repo)
    idx.initialize(force=True)

    with IndexDatabase(repo) as db:
        retriever = ContextRetriever(db)
        api_selected = {
            f["path"]
            for f in retriever.build_context("change API response shape", 1000, 3).get(
                "relevant_files", []
            )
        }
        response_only = retriever.rank_files("change response wording", 10)

    assert "backend/routes.py" in api_selected
    assert all("api" not in reason for item in response_only for reason in item.reasons)


def test_configuration_task_prefers_project_config_over_noisy_symbols(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "[project.optional-dependencies]\nfull = ['httpx']\n"
    )
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_urls.py").write_text(
        "\n".join(f"def test_url_path_for_{index}(): pass" for index in range(50))
    )

    Indexer(repo).initialize(force=True)

    with IndexDatabase(repo) as db:
        selected = [
            item.path
            for item in ContextRetriever(db).rank_files(
                "update pyproject optional dependencies for full install extra", 10
            )
        ]

    assert selected[0] == "pyproject.toml"


def test_exact_path_terms_survive_large_test_symbol_noise(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    middleware = repo / "app" / "middleware"
    tests = repo / "tests" / "middleware"
    middleware.mkdir(parents=True)
    tests.mkdir(parents=True)
    (middleware / "cors.py").write_text(
        "class CORSMiddleware:\n"
        "    def preflight_response(self):\n"
        "        return {'headers': 'ok'}\n"
    )
    (tests / "test_base.py").write_text(
        "\n".join(
            f"def test_response_headers_with_middleware_{index}(): pass"
            for index in range(60)
        )
    )
    (tests / "test_cors.py").write_text("def test_cors_headers(): pass\n")

    Indexer(repo).initialize(force=True)

    with IndexDatabase(repo) as db:
        selected = [
            item.path
            for item in ContextRetriever(db).rank_files(
                "change CORS middleware preflight response headers and update tests", 10
            )
        ]

    assert "app/middleware/cors.py" in selected[:3]


def test_camelcase_framework_terms_survive_generic_test_noise(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    app = repo / "app"
    tests = repo / "tests"
    middleware_tests = tests / "middleware"
    app.mkdir(parents=True)
    tests.mkdir(parents=True)
    middleware_tests.mkdir(parents=True)
    (app / "testclient.py").write_text(
        "class TestClient:\n"
        "    def websocket_connect(self):\n"
        "        return WebSocketTestSession()\n"
        "\n"
        "class WebSocketTestSession:\n"
        "    def receive(self):\n"
        "        return {'type': 'websocket.receive'}\n"
    )
    (tests / "test_testclient.py").write_text("def test_testclient_websocket_disconnect(): pass\n")
    (tests / "test_websockets.py").write_text("def test_websocket_disconnect_receive(): pass\n")
    for index in range(20):
        (middleware_tests / f"test_noise_{index}.py").write_text(
            "\n".join(
                f"def test_middleware_receive_loop_{inner}(): pass"
                for inner in range(8)
            )
        )

    Indexer(repo).initialize(force=True)

    with IndexDatabase(repo) as db:
        selected = [
            item.path
            for item in ContextRetriever(db).rank_files(
                "fix WebSocket disconnect handling in TestClient receive loop", 10
            )
        ]

    assert "app/testclient.py" in selected[:3]
    assert {"tests/test_testclient.py", "tests/test_websockets.py"} & set(selected[:6])
