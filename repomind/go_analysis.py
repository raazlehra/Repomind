"""Local Go package topology from compact indexed evidence, without filesystem reads."""

from __future__ import annotations

import hashlib
import json
import posixpath
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from repomind.database import IndexDatabase
from repomind.parsers.go import GO_REVISION, import_path
from repomind.scanner import is_executable_test_path

GO_META_KEY = "go.analysis.v1"
MAX_GO_FILES = 5_000
MAX_GO_RECORDS = 20_000
MAX_GO_EDGES = 20_000
MAX_GO_PACKAGE_FILES = 256
MAX_GO_MODULES = 256
MAX_GO_WORKSPACES = 64
MAX_GO_METADATA_BYTES = 2_000_000


def go_graph_fingerprint(database: IndexDatabase) -> str:
    digest = hashlib.sha256()
    rows = database.connection.execute(
        """SELECT source_file_id,target_file_id,source_symbol_id,target_symbol_id,kind,confidence,source
           FROM dependencies WHERE kind LIKE 'go-%'
           ORDER BY source_file_id,target_file_id,kind,confidence,source LIMIT ?""", (MAX_GO_EDGES + 1,),
    )
    for row in rows:
        digest.update(json.dumps(tuple(row), separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def local_directory(owner: str, value: str) -> str | None:
    if (
        not value
        or len(value) > 1_000
        or any(c in value for c in "\\:\x00*?[]{}")
        or value.startswith("/")
    ):
        return None
    target = posixpath.normpath(posixpath.join(owner, value))
    if (
        target == ".."
        or target.startswith("../")
        or any(p in {".git", ".repomind", "vendor"} for p in target.split("/"))
    ):
        return None
    return target


def load_go_analysis(database: IndexDatabase) -> dict[str, Any]:
    raw = database.get_meta(GO_META_KEY)
    if raw is None or len(raw.encode("utf-8")) > MAX_GO_METADATA_BYTES:
        return {
            "files": {},
            "truncated": False,
            "notes": ["Go index evidence unavailable; refresh the index."],
        }
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        value = None
    if not isinstance(value, dict) or not isinstance(value.get("files"), dict):
        return {"files": {}, "truncated": True, "notes": ["Invalid Go index evidence."]}
    return value


@dataclass(frozen=True, slots=True)
class Module:
    root: str
    name: str
    manifest: str


class GoTopology:
    def __init__(self, database: IndexDatabase) -> None:
        self.database = database
        self.truncated = False
        self.notes: set[str] = set()
        rows = list(
            database.connection.execute(
                """SELECT id,path,is_test,parse_error,summary FROM files
               WHERE language='go' OR path='go.mod' OR path='go.work'
                 OR path LIKE '%/go.mod' OR path LIKE '%/go.work'
               ORDER BY path LIMIT ?""",
                (MAX_GO_FILES + 1,),
            )
        )
        self.rows = {str(row["path"]): row for row in rows[:MAX_GO_FILES]}
        self.by_id = {int(row["id"]): path for path, row in self.rows.items()}
        self.records: dict[str, list[Any]] = defaultdict(list)
        self.imports: dict[str, list[str]] = defaultdict(list)
        self.info: dict[str, dict[str, Any]] = {}
        self.modules: dict[str, Module] = {}
        self._view_cache: dict[str, tuple[dict[str, Module], str | None]] = {}
        self.module_roots = {
            PurePosixPath(path).parent.as_posix()
            for path in self.rows
            if PurePosixPath(path).name == "go.mod"
        }
        self.workspaces = {
            PurePosixPath(path).parent.as_posix(): path
            for path in self.rows
            if PurePosixPath(path).name == "go.work"
        }
        if (
            len(rows) > MAX_GO_FILES
            or len(self.module_roots) > MAX_GO_MODULES
            or len(self.workspaces) > MAX_GO_WORKSPACES
        ):
            self.truncated = True
            self.notes.add(
                "Go file/module/workspace budget exceeded; local topology is unsupported."
            )
            return
        for query, destination in (
            (
                "SELECT file_id,kind,target,evidence FROM \"references\" WHERE kind LIKE 'go-%' ORDER BY id LIMIT ?",
                self.records,
            ),
            (
                "SELECT imports.file_id,imports.module FROM imports JOIN files ON files.id=imports.file_id WHERE files.language='go' ORDER BY imports.id LIMIT ?",
                self.imports,
            ),
        ):
            records = list(database.connection.execute(query, (MAX_GO_RECORDS + 1,)))
            if len(records) > MAX_GO_RECORDS:
                self.truncated = True
                self.notes.add("Go evidence budget exceeded; local topology is unsupported.")
                return
            for record in records:
                if int(record["file_id"]) in self.by_id:
                    path = self.by_id[int(record["file_id"])]
                    destination[path].append(
                        record if destination is self.records else str(record["module"])
                    )
        self._modules()
        self._packages()

    def _records(self, path: str, kind: str) -> list[Any]:
        return [r for r in self.records[path] if r["kind"] == f"go-{kind}"]

    def _modules(self) -> None:
        names: dict[str, list[str]] = defaultdict(list)
        for path, row in self.rows.items():
            if PurePosixPath(path).name != "go.mod" or row["parse_error"]:
                continue
            declarations = self._records(path, "module")
            if len(declarations) == 1:
                root = PurePosixPath(path).parent.as_posix()
                self.modules[root] = Module(root, str(declarations[0]["target"]), path)
                names[self.modules[root].name].append(root)
        for name, roots in names.items():
            if len(roots) > 1:
                self.notes.add(f"Ambiguous duplicate Go module identity: {name}")
                for root in roots:
                    del self.modules[root]

    @staticmethod
    def _owner(path: str, roots: set[str]) -> str | None:
        parent = PurePosixPath(path).parent
        for candidate in (parent, *parent.parents):
            value = candidate.as_posix()
            if value in roots:
                return value
        return None

    def _workspace(self, module: Module) -> tuple[str | None, dict[str, Module], str | None]:
        root = self._owner(module.manifest, set(self.workspaces))
        if root is None:
            return None, {}, None
        path = self.workspaces[root]
        if self.rows[path]["parse_error"]:
            return path, {}, "Malformed Go workspace"
        members: dict[str, Module] = {}
        for reference in self._records(path, "use"):
            directory = local_directory(root, str(reference["target"]))
            if directory is None or directory not in self.modules:
                return path, {}, "Unresolved or outside-root Go workspace member"
            member = self.modules[directory]
            if member.name in members:
                return path, {}, "Duplicate Go workspace member"
            members[member.name] = member
        if module.name not in members or members[module.name].root != module.root:
            return path, {}, "Module is not a member of the enclosing Go workspace"
        return path, members, None

    def _views(self, module: Module) -> tuple[dict[str, Module], str | None]:
        if module.root not in self._view_cache:
            self._view_cache[module.root] = self._build_views(module)
        return self._view_cache[module.root]

    def _build_views(self, module: Module) -> tuple[dict[str, Module], str | None]:
        workspace, members, problem = self._workspace(module)
        if problem == "Module is not a member of the enclosing Go workspace":
            # A local replacement can be a dependency without being a workspace
            # main module. Its declarations remain useful; direct commands from
            # that directory are withheld separately.
            workspace, members, problem = None, {}, None
        if problem:
            return {}, problem
        views = {module.name: module, **members}
        requires = {str(r["target"]) for r in self._records(module.manifest, "require")}
        # A workspace replacement takes precedence. Version-specific conflicts are
        # conservatively unresolved; no module/version solver is invoked.
        replacements: dict[str, list[tuple[str, Any]]] = defaultdict(list)
        for manifest in (module.manifest, workspace):
            if manifest is None:
                continue
            grouped: dict[str, list[tuple[str, Any]]] = defaultdict(list)
            for reference in self._records(manifest, "replace"):
                grouped[str(reference["target"])].append((manifest, reference))
            replacements.update(grouped)
        for name, entries in replacements.items():
            if name not in requires and name not in members:
                continue
            if len(entries) != 1:
                self.notes.add(f"Ambiguous Go replacement for {name}")
                return {}, "Ambiguous Go module replacement"
            manifest, record = entries[0]
            data = json.loads(str(record["evidence"]))
            version = data["old_version"]
            required_versions = {
                str(r["evidence"])
                for r in self._records(module.manifest, "require")
                if r["target"] == name
            }
            if version and required_versions != {version}:
                self.notes.add(f"Version-specific Go replacement unresolved: {name}")
                return {}, "Version-specific Go module replacement is unresolved"
            directory = (
                local_directory(PurePosixPath(manifest).parent.as_posix(), str(data["target"]))
                if not data["version"] and str(data["target"]).startswith(("./", "../"))
                else None
            )
            target = self.modules.get(directory or "")
            if target is None or target.name != name:
                views.pop(name, None)
                self.notes.add(f"External, outside-root, or mismatched Go replacement: {name}")
                if not data["version"]:
                    return {}, "Local Go replacement is outside-root, unindexed, or mismatched"
                continue
            views[name] = target
        return views, None

    def _packages(self) -> None:
        groups: dict[str, list[str]] = defaultdict(list)
        for path in self.rows:
            if path.endswith(".go"):
                groups[PurePosixPath(path).parent.as_posix()].append(path)
        for directory, paths in groups.items():
            owner = self._owner(paths[0], self.module_roots)
            module = self.modules.get(owner or "")
            reason = "Missing, malformed, or ambiguous Go module"
            if module is not None:
                _, reason_from_view = self._views(module)
                reason = reason_from_view or ""
            if len(paths) > MAX_GO_PACKAGE_FILES:
                reason = "Go package file budget exceeded"
                self.truncated = True
            declarations: dict[str, str] = {}
            for path in paths:
                records = self._records(path, "package")
                if len(records) == 1:
                    declarations[path] = str(records[0]["target"])
                if self.rows[path]["parse_error"] or not str(self.rows[path]["summary"]).startswith(
                    GO_REVISION
                ):
                    reason = "Malformed or legacy Go package evidence; refresh required"
            production = {
                name for path, name in declarations.items() if not path.endswith("_test.go")
            }
            if len(production) != 1:
                reason = "Missing or conflicting Go production package declarations"
            package = next(iter(production), "")
            if any(
                name not in {package, package + "_test"}
                for path, name in declarations.items()
                if path.endswith("_test.go")
            ):
                reason = "Conflicting Go test package declarations"
            for path in paths:
                limitations = [str(r["target"]) for r in self._records(path, "limitation")]
                own_reason = reason or (", ".join(limitations) if limitations else "")
                if path.endswith("_test.go") and not is_executable_test_path(path):
                    own_reason = "Go test support path is not an executable target"
                if PurePosixPath(path).name.startswith(("_", ".")):
                    own_reason = "Go ignores this source filename"
                relative = posixpath.relpath(directory, owner or ".")
                if relative != "." and not import_path(relative):
                    own_reason = "Unsupported Go package directory"
                if own_reason:
                    self.notes.add(f"{path}: {own_reason}")
                self.info[path] = {
                    "supported": not own_reason,
                    "reason": own_reason,
                    "module": owner,
                    "package": directory,
                    "name": package,
                    "external_test": declarations.get(path) == package + "_test",
                    "target": "." if relative == "." else "./" + relative,
                    "runner_supported": not own_reason
                    and module is not None
                    and self._workspace(module)[2] is None,
                    "runner_reason": self._workspace(module)[2]
                    if module is not None
                    else own_reason,
                }
        for module in self.modules.values():
            _, _, workspace_issue = self._workspace(module)
            _, structural_issue = self._views(module)
            self.info[module.manifest] = {
                "supported": not structural_issue,
                "reason": structural_issue or "",
                "module": module.root,
                "runner_supported": structural_issue is None and workspace_issue is None,
                "runner_reason": workspace_issue,
            }
        for workspace in self.workspaces.values():
            member_modules = [
                m for m in self.modules.values() if self._workspace(m)[0] == workspace and self._workspace(m)[2] != "Module is not a member of the enclosing Go workspace"
            ]
            supported = bool(member_modules) and all(
                not self._workspace(m)[2] and not self._views(m)[1] for m in member_modules
            )
            self.info[workspace] = {
                "supported": supported,
                "reason": "" if supported else "Unresolved Go workspace membership",
            }

    def edges(self) -> list[tuple[int, int, str, float, str]]:
        result: list[tuple[int, int, str, float, str]] = []
        seen: set[tuple[int, int, str]] = set()

        def add(source: str, target: str, kind: str, confidence: float, why: str) -> None:
            if self.truncated or source == target:
                return
            key = (int(self.rows[source]["id"]), int(self.rows[target]["id"]), kind)
            if key in seen:
                return
            if len(result) >= MAX_GO_EDGES:
                self.truncated = True
                self.notes.add("Go edge budget exceeded; local topology is partial/unsupported.")
                return
            seen.add(key)
            result.append((*key[:2], kind, confidence, why))

        if self.truncated:
            return result
        production: dict[str, list[str]] = defaultdict(list)
        for path, info in self.info.items():
            if path.endswith(".go") and not path.endswith("_test.go") and info["supported"]:
                production[str(info["package"])].append(path)
        for path, info in self.info.items():
            if not info["supported"] or not path.endswith(".go"):
                continue
            module = self.modules[str(info["module"])]
            views, _ = self._views(module)
            add(path, module.manifest, "go-module", 1.0, f"Go module ownership:{module.name}")
            package = str(info["package"])
            if path.endswith("_test.go") and not info["external_test"]:
                for target in production[package]:
                    add(
                        path,
                        target,
                        "go-package-test",
                        0.8,
                        "Go same-package test membership; runtime coverage unknown",
                    )
            for imported in self.imports[path]:
                matches = [
                    name for name in views if imported == name or imported.startswith(name + "/")
                ]
                if not matches:
                    # Imports remain stored, unresolved. They are not guessed by suffix.
                    continue
                name = max(matches, key=len)
                target_module = views[name]
                suffix = imported[len(name) :].lstrip("/")
                target_dir = (
                    posixpath.join(target_module.root, suffix) if suffix else target_module.root
                )
                target_dir = posixpath.normpath(target_dir)
                targets = production.get(target_dir, [])
                targets = [p for p in targets if self.info[p]["module"] == target_module.root]
                if not targets:
                    self.notes.add(f"Unresolved local Go import: {path} -> {imported}")
                for target in targets:
                    add(path, target, "go-import", 1.0, f"Go local package import:{imported}")
                    if path.endswith("_test.go"):
                        add(
                            path,
                            target,
                            "go-test-target",
                            0.9,
                            f"Go test imports local package:{imported}",
                        )
        for module in self.modules.values():
            workspace, members, reason = self._workspace(module)
            if workspace and not reason:
                add(
                    module.manifest,
                    workspace,
                    "go-workspace",
                    1.0,
                    "Indexed Go workspace membership",
                )
            views, problem = self._views(module)
            if problem:
                continue
            for name in sorted(
                {str(r["target"]) for r in self._records(module.manifest, "require")}
            ):
                if name in views:
                    add(
                        module.manifest,
                        views[name].manifest,
                        "go-require",
                        1.0,
                        f"Go local required module:{name}",
                    )
            for name, replacement_module in views.items():
                if name not in members and replacement_module.root != module.root:
                    add(
                        module.manifest,
                        replacement_module.manifest,
                        "go-replace",
                        1.0,
                        f"Go local module replacement:{name}",
                    )
        return result

    def save(self, edge_count: int) -> None:
        value = {
            "files": self.info,
            "truncated": self.truncated,
            "notes": sorted(self.notes)[:64],
            "edge_count": edge_count,
            "edge_fingerprint": go_graph_fingerprint(self.database),
            "limits": {
                "files": MAX_GO_FILES,
                "records": MAX_GO_RECORDS,
                "edges": MAX_GO_EDGES,
                "package_files": MAX_GO_PACKAGE_FILES,
                "modules": MAX_GO_MODULES,
                "workspaces": MAX_GO_WORKSPACES,
                "metadata_bytes": MAX_GO_METADATA_BYTES,
            },
            "scope": "Indexed local packages only; external/standard-library imports and runtime coverage remain unresolved.",
        }
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if len(raw.encode("utf-8")) > MAX_GO_METADATA_BYTES:
            raw = json.dumps(
                {
                    "files": {},
                    "truncated": True,
                    "notes": ["Go metadata budget exceeded"],
                    "edge_count": edge_count,
                    "edge_fingerprint": go_graph_fingerprint(self.database),
                }
            )
        self.database.set_meta(GO_META_KEY, raw)


def go_graph_needs_refresh(database: IndexDatabase) -> bool:
    raw = load_go_analysis(database)
    expected = raw.get("edge_count")
    if expected is None:
        return True
    return bool(raw.get("edge_fingerprint") != go_graph_fingerprint(database))
