from __future__ import annotations

from pathlib import Path

from repomind.integration import AGENTS_BEGIN, AGENTS_END, SKILL_BEGIN, SKILL_END, install_codex


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


def test_rebrand_preserves_user_content_and_legacy_marked_agents(tmp_path: Path) -> None:
    skill = tmp_path / ".codex" / "skills" / "repomind" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    prefix = "---\nname: repomind\n---\nUser introduction.\n"
    suffix = "\nUser-specific instructions.\n"
    skill.write_text(prefix + SKILL_BEGIN + "\nOld managed copy\n" + SKILL_END + suffix)
    agents = tmp_path / "AGENTS.md"
    old_agents = f"# Custom\n{AGENTS_BEGIN}\n## RepoMind\nLegacy instructions\n{AGENTS_END}\n"
    agents.write_text(old_agents)

    first = install_codex(tmp_path)
    second = install_codex(tmp_path)

    assert first.skill_action == "updated RepoMind-managed skill"
    assert second.skill_action == "unchanged"
    assert skill.read_text().startswith(prefix + SKILL_BEGIN)
    assert skill.read_text().endswith(SKILL_END + suffix)
    assert "Lehraz Atlas Free" in skill.read_text()
    assert skill.read_text().count(SKILL_BEGIN) == 1
    assert agents.read_text() == old_agents
    assert first.agents_action == second.agents_action == "unchanged"


def test_ambiguous_skill_markers_do_not_overwrite_user_content(tmp_path: Path) -> None:
    skill = tmp_path / ".codex" / "skills" / "repomind" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    content = SKILL_END + "\nCustom\n" + SKILL_BEGIN
    skill.write_text(content)
    result = install_codex(tmp_path)
    assert result.skill_action == "preserved existing unmanaged skill"
    assert skill.read_text() == content
