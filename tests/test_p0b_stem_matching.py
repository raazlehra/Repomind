from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.test_impact import TestImpactLimits, analyze_test_impact

TestImpactLimits.__test__ = False  # type: ignore[attr-defined]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _analyze(
    repo: Path, changed: list[str], limits: TestImpactLimits | None = None
) -> dict[str, Any]:
    with IndexDatabase(repo) as database:
        return analyze_test_impact(database, changed, limits=limits)


def test_generic_stem_collision_elimination(tmp_path: Path) -> None:
    """When a generic file (e.g. src/middleware/mount/index.ts) changes,

    unrelated components with identical stems (src/middleware/basic-auth/index.test.ts)
    must NOT be admitted into targeted tests solely by generic basename equality.
    The legitimate component test (src/middleware/mount/index.test.ts) must be preserved.
    """
    repo = tmp_path / "generic_stem_repo"
    _write(
        repo / "package.json",
        json.dumps({
            "name": "stem-demo",
            "scripts": {"test": "vitest run"},
            "devDependencies": {"vitest": "^1.0.0"},
        }),
    )
    # Changed component: mount
    _write(repo / "src" / "middleware" / "mount" / "index.ts", "export const mount = () => 'mount';\n")
    _write(
        repo / "src" / "middleware" / "mount" / "index.test.ts",
        "import { mount } from './index';\ndescribe('mount', () => { it('works', () => mount()); });\n",
    )

    # Unrelated components with colliding generic stem 'index'
    _write(repo / "src" / "middleware" / "basic-auth" / "index.ts", "export const basicAuth = () => 'auth';\n")
    _write(
        repo / "src" / "middleware" / "basic-auth" / "index.test.ts",
        "import { basicAuth } from './index';\ndescribe('auth', () => { it('works', () => basicAuth()); });\n",
    )

    _write(repo / "src" / "middleware" / "bearer-auth" / "index.ts", "export const bearerAuth = () => 'bearer';\n")
    _write(
        repo / "src" / "middleware" / "bearer-auth" / "index.test.ts",
        "import { bearerAuth } from './index';\ndescribe('bearer', () => { it('works', () => bearerAuth()); });\n",
    )

    Indexer(repo).initialize()

    report = _analyze(repo, ["src/middleware/mount/index.ts"])

    discovered_files = {item["file"] for item in report["existing_tests"]}

    # 1. Mount's own test MUST be discovered
    assert "src/middleware/mount/index.test.ts" in discovered_files

    # 2. Unrelated basic-auth and bearer-auth tests MUST NOT be discovered solely on 'index' stem!
    assert "src/middleware/basic-auth/index.test.ts" not in discovered_files
    assert "src/middleware/bearer-auth/index.test.ts" not in discovered_files

    # 3. Targeted command only includes mount's test
    targeted = next(cmd for cmd in report["recommended_commands"] if cmd["scope"] == "targeted")
    assert "src/middleware/mount/index.test.ts" in targeted["related_tests"]
    assert "src/middleware/basic-auth/index.test.ts" not in targeted["related_tests"]
    assert "src/middleware/bearer-auth/index.test.ts" not in targeted["related_tests"]


def test_mirrored_src_tests_layout_matching(tmp_path: Path) -> None:
    """When a component has tests in a mirrored tests/ directory (parallel hierarchy),

    filename matching correctly links tests/auth/index.test.ts to src/auth/index.ts.
    """
    repo = tmp_path / "mirrored_repo"
    _write(
        repo / "package.json",
        json.dumps({
            "name": "mirror-demo",
            "scripts": {"test": "vitest run"},
            "devDependencies": {"vitest": "^1.0.0"},
        }),
    )
    _write(repo / "src" / "auth" / "index.ts", "export const auth = () => true;\n")
    _write(
        repo / "tests" / "auth" / "index.test.ts",
        "describe('auth', () => { it('works', () => {}); });\n",
    )
    # Unrelated mirrored component
    _write(repo / "src" / "billing" / "index.ts", "export const billing = () => true;\n")
    _write(
        repo / "tests" / "billing" / "index.test.ts",
        "describe('billing', () => { it('works', () => {}); });\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["src/auth/index.ts"])
    discovered = {item["file"] for item in report["existing_tests"]}

    assert "tests/auth/index.test.ts" in discovered
    assert "tests/billing/index.test.ts" not in discovered


def test_deep_nested_directories_collision_rejection(tmp_path: Path) -> None:
    """Deeply nested components sharing generic stems like mod.rs, main.py, or app.ts

    must not collide across unrelated directory trees.
    """
    repo = tmp_path / "deep_nested_repo"
    _write(
        repo / "package.json",
        json.dumps({
            "name": "nested-demo",
            "scripts": {"test": "vitest run"},
            "devDependencies": {"vitest": "^1.0.0"},
        }),
    )
    _write(repo / "src" / "modules" / "users" / "account" / "index.ts", "export const data = 1;\n")
    _write(
        repo / "src" / "modules" / "users" / "account" / "index.test.ts",
        "describe('users account', () => { it('ok', () => {}); });\n",
    )
    _write(repo / "src" / "modules" / "orders" / "account" / "index.ts", "export const odata = 2;\n")
    _write(
        repo / "src" / "modules" / "orders" / "account" / "index.test.ts",
        "describe('orders account', () => { it('ok', () => {}); });\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["src/modules/users/account/index.ts"])
    discovered = {item["file"] for item in report["existing_tests"]}

    assert "src/modules/users/account/index.test.ts" in discovered
    assert "src/modules/orders/account/index.test.ts" not in discovered


def test_multiple_languages_and_extension_variants(tmp_path: Path) -> None:
    """Extension variants (e.g. index.ts <-> index.test.tsx) within the same component match,

    while distinct components do not.
    """
    repo = tmp_path / "ext_variants_repo"
    _write(
        repo / "package.json",
        json.dumps({
            "name": "ext-demo",
            "scripts": {"test": "vitest run"},
            "devDependencies": {"vitest": "^1.0.0"},
        }),
    )
    _write(repo / "src" / "ui" / "button" / "index.ts", "export const Button = () => null;\n")
    _write(
        repo / "src" / "ui" / "button" / "index.test.tsx",
        "describe('Button', () => { it('renders', () => {}); });\n",
    )
    _write(repo / "src" / "ui" / "modal" / "index.tsx", "export const Modal = () => null;\n")
    _write(
        repo / "src" / "ui" / "modal" / "index.test.tsx",
        "describe('Modal', () => { it('renders', () => {}); });\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["src/ui/button/index.ts"])
    discovered = {item["file"] for item in report["existing_tests"]}

    assert "src/ui/button/index.test.tsx" in discovered
    assert "src/ui/modal/index.test.tsx" not in discovered


def test_cross_directory_direct_import_preserved(tmp_path: Path) -> None:
    """When a test in an unrelated directory directly imports the changed module,

    it is preserved via dependency evidence even though filename stems differ.
    """
    repo = tmp_path / "cross_import_repo"
    _write(
        repo / "package.json",
        json.dumps({
            "name": "cross-import-demo",
            "scripts": {"test": "vitest run"},
            "devDependencies": {"vitest": "^1.0.0"},
        }),
    )
    _write(repo / "src" / "middleware" / "mount" / "index.ts", "export const mount = () => 'mount';\n")
    _write(
        repo / "src" / "middleware" / "mount" / "index.test.ts",
        "import { mount } from './index';\ndescribe('mount', () => { mount(); });\n",
    )
    # Integration test in integration/ imports mount
    _write(
        repo / "tests" / "integration" / "e2e_mount.test.ts",
        "import { mount } from '../../src/middleware/mount/index';\ndescribe('e2e', () => { mount(); });\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["src/middleware/mount/index.ts"])
    discovered = {item["file"] for item in report["existing_tests"]}

    # Sibling filename match
    assert "src/middleware/mount/index.test.ts" in discovered
    # Direct import cross-directory dependency
    assert "tests/integration/e2e_mount.test.ts" in discovered
    e2e_item = next(item for item in report["existing_tests"] if item["file"] == "tests/integration/e2e_mount.test.ts")
    assert any(ev["kind"] == "dependency" for ev in e2e_item["evidence"])
