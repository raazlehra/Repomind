from __future__ import annotations

import json
from pathlib import Path

from repomind.cli import main


def test_cli_init_status_map_context_impact(python_repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["init", str(python_repo), "--format", "json"]) == 0
    init_data = json.loads(capsys.readouterr().out)
    assert init_data["indexed_files"] > 0

    assert main(["status", "-C", str(python_repo), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["index_healthy"] is True

    assert main(["map", "-C", str(python_repo), "--symbols", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["files"]

    assert (
        main(
            ["context", "fix login", "-C", str(python_repo), "--budget", "750", "--format", "json"]
        )
        == 0
    )
    context = json.loads(capsys.readouterr().out)
    assert context["relevant_files"]

    assert main(["impact", "AuthService.login", "-C", str(python_repo), "--format", "json"]) == 0
    assert "direct_dependents" in json.loads(capsys.readouterr().out)


def test_cli_not_indexed_error(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["status", "-C", str(tmp_path)]) == 2
    assert "Repository is not indexed. Run: repomind init" in capsys.readouterr().err


def test_cli_install_codex_is_idempotent(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["install-codex", str(tmp_path), "--format", "json"]) == 0
    capsys.readouterr()
    assert main(["install-codex", str(tmp_path), "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["agents"]["action"] == "unchanged"
