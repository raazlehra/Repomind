from __future__ import annotations

from pathlib import Path

from repomind.integration import AGENTS_BEGIN, SKILL_BEGIN, install_codex


def test_install_codex_creates_skill_and_agents(tmp_path: Path) -> None:
    result = install_codex(tmp_path)
    assert result.skill_action == "created"
    assert SKILL_BEGIN in (tmp_path / result.skill_path).read_text()
    assert AGENTS_BEGIN in (tmp_path / "AGENTS.md").read_text()


def test_agents_md_append_is_idempotent(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Existing\n\nKeep this.\n")
    first = install_codex(tmp_path)
    content = agents.read_text()
    second = install_codex(tmp_path)
    assert first.agents_action == "appended"
    assert second.agents_action == "unchanged"
    assert agents.read_text() == content
    assert content.count(AGENTS_BEGIN) == 1
    assert "Keep this." in content


def test_unmanaged_skill_is_preserved(tmp_path: Path) -> None:
    skill = tmp_path / ".codex" / "skills" / "repomind" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("custom skill")
    result = install_codex(tmp_path)
    assert result.skill_action == "preserved existing unmanaged skill"
    assert skill.read_text() == "custom skill"
