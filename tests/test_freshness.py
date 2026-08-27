from __future__ import annotations

import codecs
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from mcp import Client

from repomind.cli import main
from repomind.database import IndexDatabase
from repomind.freshness import ensure_index_fresh
from repomind.indexer import Detection, Indexer
from repomind.mcp import create_server
from repomind.queries import symbol_details
from repomind.services import context as service_context
from repomind.services import status as service_status
from repomind.services import symbol as service_symbol
from repomind.utils import hash_file
from repomind.watcher import watchdog_available


def test_cli_context_auto_refreshes_modified_python_file(
    python_repo: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    Indexer(python_repo).initialize()
    auth = python_repo / "app" / "auth.py"
    auth.write_text(
        auth.read_text(encoding="utf-8")
        + "\n    def emergency_login(self) -> str:\n        return 'fresh'\n",
        encoding="utf-8",
    )

    assert main(["context", "emergency login", "-C", str(python_repo), "--format", "json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert any(item["path"] == "app/auth.py" for item in data["relevant_files"])
    assert any(item["name"].endswith("emergency_login") for item in data["important_symbols"])


def test_cli_map_auto_refreshes_new_deleted_and_renamed_files(
    python_repo: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    Indexer(python_repo).initialize()
    (python_repo / "app" / "billing.py").write_text(
        "def billing_context_target() -> bool:\n    return True\n",
        encoding="utf-8",
    )
    (python_repo / "app" / "email.py").unlink()
    (python_repo / "app" / "models.py").rename(python_repo / "app" / "entities.py")

    assert main(["map", "-C", str(python_repo), "--json"]) == 0

    paths = {item["path"] for item in json.loads(capsys.readouterr().out)["files"]}
    assert "app/billing.py" in paths
    assert "app/entities.py" in paths
    assert "app/email.py" not in paths
    assert "app/models.py" not in paths


def test_freshness_ignores_new_ignored_files(python_repo: Path) -> None:
    (python_repo / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    Indexer(python_repo).initialize()
    (python_repo / "ignored.py").write_text("def ignored_symbol() -> None:\n    pass\n")

    result = ensure_index_fresh(python_repo)

    assert result.was_stale is False
    assert result.created == 0
    with IndexDatabase(python_repo) as database:
        assert database.file_by_path("ignored.py") is None


def test_cli_symbol_auto_refreshes_modified_bom_python_file(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "service.py"
    source.write_bytes(codecs.BOM_UTF8 + b"def before() -> str:\n    return 'before'\n")
    Indexer(tmp_path).initialize()
    source.write_bytes(codecs.BOM_UTF8 + b"def after_change() -> str:\n    return 'after'\n")

    assert main(["symbol", "after_change", "-C", str(tmp_path), "--format", "json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["matches"][0]["file"] == "service.py"


def test_cli_symbol_auto_refreshes_typescript_modification(
    mixed_repo: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    Indexer(mixed_repo).initialize()
    api = mixed_repo / "frontend" / "src" / "api.ts"
    api.write_text(
        api.read_text(encoding="utf-8")
        + "\nexport function refundPayment(id: string): string {\n  return id;\n}\n",
        encoding="utf-8",
    )

    assert main(["symbol", "refundPayment", "-C", str(mixed_repo), "--format", "json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["matches"][0]["file"] == "frontend/src/api.ts"


def test_freshness_result_reports_modified_existing_python_file(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    target = python_repo / "app" / "auth.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\ndef REPOMIND_FRESHNESS_TEST_MODIFIED() -> None:\n    pass\n",
        encoding="utf-8",
    )

    result = ensure_index_fresh(python_repo)

    assert result.was_stale is True
    assert result.modified >= 1
    assert result.refreshed == 1
    with IndexDatabase(python_repo) as database:
        assert database.connection.execute(
            "SELECT 1 FROM symbols WHERE name='REPOMIND_FRESHNESS_TEST_MODIFIED'"
        ).fetchone()


def test_cli_symbol_auto_refreshes_modified_kotlin_object(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "TransactionParser.kt"
    source.write_text(
        "package com.moneycompanion.domain\n\nclass TransactionParser\n",
        encoding="utf-8",
    )
    Indexer(tmp_path).initialize()
    source.write_text(
        "package com.moneycompanion.domain\n\n"
        "object REPOMIND_FRESHNESS_TEST_MODIFIED\n\n"
        "class TransactionParser\n",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "symbol",
                "REPOMIND_FRESHNESS_TEST_MODIFIED",
                "-C",
                str(tmp_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    symbol_data = json.loads(capsys.readouterr().out)
    assert symbol_data["matches"][0]["file"] == "TransactionParser.kt"
    assert symbol_data["matches"][0]["kind"] == "object"

    assert (
        main(
            [
                "context",
                "REPOMIND_FRESHNESS_TEST_MODIFIED",
                "-C",
                str(tmp_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    context_data = json.loads(capsys.readouterr().out)
    assert any(item["path"] == "TransactionParser.kt" for item in context_data["relevant_files"])


def test_same_size_python_modification_is_detected_even_with_same_mtime(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "service.py"
    before = "def AAA_TEST() -> None:\n    pass\n"
    after = "def BBB_TEST() -> None:\n    pass\n"
    assert len(before.encode("utf-8")) == len(after.encode("utf-8"))
    source.write_text(before, encoding="utf-8")
    Indexer(tmp_path).initialize()
    original_stat = source.stat()
    source.write_text(after, encoding="utf-8")
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    assert main(["symbol", "BBB_TEST", "-C", str(tmp_path), "--format", "json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["matches"][0]["file"] == "service.py"
    with IndexDatabase(tmp_path) as database:
        old_symbol = database.connection.execute(
            "SELECT 1 FROM symbols WHERE name='AAA_TEST'"
        ).fetchone()
        assert old_symbol is None


def test_modification_reverted_before_retrieval_does_not_reparse(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    original = "def stable_symbol() -> None:\n    pass\n"
    source.write_text(original, encoding="utf-8")
    Indexer(tmp_path).initialize()
    source.write_text("def transient_symbol() -> None:\n    pass\n", encoding="utf-8")
    source.write_text(original, encoding="utf-8")

    result = ensure_index_fresh(tmp_path)
    data = service_symbol(str(tmp_path), "transient_symbol")

    assert result.modified == 0
    assert result.refreshed == 0
    assert data["matches"] == []


@pytest.mark.anyio
async def test_mcp_symbol_auto_refreshes_modified_python_file(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    target = python_repo / "app" / "auth.py"
    target.write_text(
        target.read_text(encoding="utf-8") + "\ndef mcp_modified_symbol() -> None:\n    pass\n",
        encoding="utf-8",
    )

    async with Client(create_server()) as client:
        result = await client.call_tool(
            "repomind_symbol",
            {"repository": str(python_repo), "symbol": "mcp_modified_symbol"},
        )

    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    data = result.structured_content
    assert data["freshness"]["modified"] >= 1
    assert data["matches"][0]["file"] == "app/auth.py"


def test_cli_dependencies_auto_refreshes_dependency_change(
    python_repo: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    Indexer(python_repo).initialize()
    routes = python_repo / "app" / "routes.py"
    routes.write_text(
        "from fastapi import APIRouter\n"
        "from .auth import AuthService\n"
        "from .email import EmailService\n\n"
        "router = APIRouter()\n"
        "auth_service: AuthService\n"
        "email_service: EmailService\n",
        encoding="utf-8",
    )

    assert main(["dependencies", "app/routes.py", "-C", str(python_repo), "--format", "json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert any(item["file"] == "app/email.py" for item in data["dependencies"])


def test_auto_freshness_handles_two_rapid_modifications(
    python_repo: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    Indexer(python_repo).initialize()
    target = python_repo / "app" / "auth.py"
    target.write_text(target.read_text(encoding="utf-8") + "\ndef first_change() -> None:\n    pass\n")
    target.write_text(target.read_text(encoding="utf-8") + "\ndef second_change() -> None:\n    pass\n")

    assert main(["symbol", "second_change", "-C", str(python_repo), "--format", "json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["matches"][0]["file"] == "app/auth.py"


def test_concurrent_service_context_requests_share_fresh_index(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    target = python_repo / "app" / "auth.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\ndef concurrent_freshness_target() -> None:\n    pass\n",
        encoding="utf-8",
    )

    def request_context() -> list[str]:
        data = service_context(str(python_repo), "concurrent freshness target", budget=1000)
        return [item["path"] for item in data["context"]["relevant_files"]]

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: request_context(), range(4)))

    assert all("app/auth.py" in paths for paths in results)


def test_concurrent_retrieval_callers_discover_same_stale_file_once(
    python_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Indexer(python_repo).initialize()
    target = python_repo / "app" / "auth.py"
    target.write_text(
        "from .models import User\n\n"
        "class AuthService:\n"
        "    def concurrent_saved_source(self) -> User:\n"
        "        return User(id=1, email='fresh@example.com')\n",
        encoding="utf-8",
    )
    barrier = threading.Barrier(3)
    lock = threading.Lock()
    stale_detections = 0
    original_detect_changes = Indexer.detect_changes

    def detect_with_barrier(self: Indexer, database: IndexDatabase) -> Detection:
        nonlocal stale_detections
        detection = original_detect_changes(self, database)
        if "app/auth.py" in detection.changes.modified:
            should_wait = False
            with lock:
                if stale_detections < 2:
                    stale_detections += 1
                    should_wait = True
            if should_wait:
                barrier.wait(timeout=10)
        return detection

    monkeypatch.setattr(Indexer, "detect_changes", detect_with_barrier)

    def request_symbol() -> dict[str, object]:
        return service_symbol(str(python_repo), "concurrent_saved_source")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(request_symbol) for _ in range(2)]
        barrier.wait(timeout=10)
        results = [future.result(timeout=10) for future in futures]

    assert stale_detections == 2
    assert all(result["matches"][0]["file"] == "app/auth.py" for result in results)
    _assert_index_matches_file(
        python_repo,
        "app/auth.py",
        "concurrent_saved_source",
        expected_hash=hash_file(target),
    )
    _assert_no_duplicate_index_rows(python_repo)


def test_retrieval_never_observes_half_completed_incremental_refresh(
    python_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Indexer(python_repo).initialize()
    target = python_repo / "app" / "auth.py"
    target.write_text("def atomic_new_symbol() -> None:\n    pass\n", encoding="utf-8")
    deletes_visible = threading.Event()
    allow_insert = threading.Event()
    original_replace_parse_data = IndexDatabase.replace_parse_data

    def replace_parse_data_with_pause(
        self: IndexDatabase, file_id: int, result: object
    ) -> None:
        path_row = self.connection.execute("SELECT path FROM files WHERE id=?", (file_id,)).fetchone()
        if path_row and str(path_row["path"]) == "app/auth.py":
            self.connection.execute("DELETE FROM dependencies WHERE source_file_id = ?", (file_id,))
            self.connection.execute('DELETE FROM "references" WHERE file_id = ?', (file_id,))
            self.connection.execute("DELETE FROM imports WHERE file_id = ?", (file_id,))
            self.connection.execute("DELETE FROM routes WHERE file_id = ?", (file_id,))
            self.connection.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
            deletes_visible.set()
            assert allow_insert.wait(timeout=10)
        original_replace_parse_data(self, file_id, result)  # type: ignore[arg-type]

    monkeypatch.setattr(IndexDatabase, "replace_parse_data", replace_parse_data_with_pause)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(ensure_index_fresh, python_repo)
        assert deletes_visible.wait(timeout=10)
        with IndexDatabase(python_repo) as reader:
            data = symbol_details(reader, "AuthService")
            assert data["matches"][0]["file"] == "app/auth.py"
            assert symbol_details(reader, "atomic_new_symbol")["matches"] == []
        allow_insert.set()
        future.result(timeout=10)

    assert service_symbol(str(python_repo), "atomic_new_symbol")["matches"][0]["file"] == "app/auth.py"
    _assert_no_duplicate_index_rows(python_repo)


@pytest.mark.skipif(not watchdog_available(), reason="watchdog is not installed")
@pytest.mark.parametrize(
    ("case", "query", "expected_present"),
    (
        ("new", "watch_new_symbol", True),
        ("modified", "watch_modified_symbol", True),
        ("delete", "delete_me", False),
    ),
)
def test_watch_process_and_retrieval_freshness_overlap(
    tmp_path: Path, case: str, query: str, expected_present: bool
) -> None:
    repo = tmp_path / f"watch_{case}"
    repo.mkdir()
    (repo / "service.py").write_text(
        "def stable_symbol() -> None:\n    pass\n\ndef delete_me() -> None:\n    pass\n",
        encoding="utf-8",
    )
    Indexer(repo).initialize()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "repomind",
            "watch",
            "-C",
            str(repo),
            "--debounce",
            "0.01",
        ],
        cwd=Path(__file__).parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_watcher_start(process)
        if case == "new":
            (repo / "new_module.py").write_text(
                "def watch_new_symbol() -> None:\n    pass\n", encoding="utf-8"
            )
        elif case == "modified":
            (repo / "service.py").write_text(
                "def stable_symbol() -> None:\n    pass\n"
                "def watch_modified_symbol() -> None:\n    pass\n",
                encoding="utf-8",
            )
        else:
            (repo / "service.py").write_text(
                "def stable_symbol() -> None:\n    pass\n", encoding="utf-8"
            )

        data = service_symbol(str(repo), query)
        assert bool(data["matches"]) is expected_present
        _wait_for_clean_status(repo)
        _assert_no_duplicate_index_rows(repo)
        assert service_status(str(repo))["index_health"] == "ok"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_parse_error_during_auto_freshness_is_reported_but_retrieval_continues(
    tmp_path: Path,
) -> None:
    healthy_a = tmp_path / "healthy_a.py"
    healthy_b = tmp_path / "healthy_b.py"
    healthy_a.write_text("def healthy_a_symbol() -> str:\n    return 'ok'\n", encoding="utf-8")
    healthy_b.write_text("def healthy_b_symbol() -> str:\n    return 'ok'\n", encoding="utf-8")
    Indexer(tmp_path).initialize()
    healthy_a.write_text("def healthy_a_symbol(:\n", encoding="utf-8")

    data = service_context(str(tmp_path), "healthy_b_symbol", budget=1000)

    assert data["freshness"]["status"] == "partial"
    assert data["freshness"]["was_stale"] is True
    assert data["freshness"]["parse_errors"] == 1
    assert data["freshness"]["indexed_parse_errors"] == 1
    assert data["context"]["relevant_files"]
    assert service_symbol(str(tmp_path), "healthy_a_symbol")["matches"] == []
    assert service_symbol(str(tmp_path), "healthy_b_symbol")["matches"][0]["file"] == "healthy_b.py"
    assert service_context(str(tmp_path), "healthy_b_symbol", budget=1000)["freshness"][
        "status"
    ] == "partial"
    with IndexDatabase(tmp_path) as database:
        row = database.file_by_path("healthy_a.py")
        assert row is not None
        assert row["parse_error"]


def test_auto_freshness_recovers_after_parser_error_is_fixed(tmp_path: Path) -> None:
    healthy_a = tmp_path / "healthy_a.py"
    healthy_b = tmp_path / "healthy_b.py"
    healthy_a.write_text("def before_recovery() -> str:\n    return 'before'\n", encoding="utf-8")
    healthy_b.write_text("def healthy_b_symbol() -> str:\n    return 'ok'\n", encoding="utf-8")
    Indexer(tmp_path).initialize()
    healthy_a.write_text("def before_recovery(:\n", encoding="utf-8")
    partial = service_context(str(tmp_path), "healthy_b_symbol", budget=1000)
    assert partial["freshness"]["status"] == "partial"

    healthy_a.write_text("def after_recovery() -> str:\n    return 'after'\n", encoding="utf-8")
    recovered = service_symbol(str(tmp_path), "after_recovery")

    assert recovered["freshness"]["status"] == "refreshed"
    assert recovered["freshness"]["indexed_parse_errors"] == 0
    assert recovered["matches"][0]["file"] == "healthy_a.py"
    with IndexDatabase(tmp_path) as database:
        row = database.file_by_path("healthy_a.py")
        assert row is not None
        assert row["parse_error"] is None


def _assert_index_matches_file(
    repository: Path, relative_path: str, symbol_name: str, expected_hash: str
) -> None:
    with IndexDatabase(repository) as database:
        row = database.file_by_path(relative_path)
        assert row is not None
        assert row["content_hash"] == expected_hash
        symbols = [
            str(item["name"])
            for item in database.connection.execute(
                """SELECT name FROM symbols
                   WHERE file_id=? ORDER BY line_start, name""",
                (int(row["id"]),),
            )
        ]
        assert symbol_name in symbols


def _assert_no_duplicate_index_rows(repository: Path) -> None:
    duplicate_queries = {
        "symbols": """SELECT file_id, qualified_name, kind, line_start, COUNT(*)
                      FROM symbols
                      GROUP BY file_id, qualified_name, kind, line_start HAVING COUNT(*) > 1""",
        "imports": """SELECT file_id, module, imported_name, alias, line, COUNT(*)
                      FROM imports
                      GROUP BY file_id, module, imported_name, alias, line HAVING COUNT(*) > 1""",
        "routes": """SELECT file_id, method, path, handler, line, COUNT(*)
                     FROM routes
                     GROUP BY file_id, method, path, handler, line HAVING COUNT(*) > 1""",
        "dependencies": """SELECT source_file_id, target_file_id, source_symbol_id,
                                  target_symbol_id, kind, source, COUNT(*)
                           FROM dependencies
                           GROUP BY source_file_id, target_file_id, source_symbol_id,
                                    target_symbol_id, kind, source HAVING COUNT(*) > 1""",
    }
    with IndexDatabase(repository) as database:
        assert database.integrity_check() == "ok"
        for table, query in duplicate_queries.items():
            assert database.connection.execute(query).fetchall() == [], table


def _wait_for_watcher_start(process: subprocess.Popen[str]) -> None:
    assert process.stderr is not None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        line = process.stderr.readline()
        if "Watching" in line:
            return
        if process.poll() is not None:
            raise AssertionError(f"watch process exited early: {line}")
    raise AssertionError("watch process did not start")


def _wait_for_clean_status(repository: Path) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = service_status(str(repository))
        if status["changed"] == 0 and status["new"] == 0 and status["deleted"] == 0:
            return
        time.sleep(0.05)
    raise AssertionError(f"repository did not become clean: {service_status(str(repository))}")
