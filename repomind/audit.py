from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from repomind import __version__
from repomind.database import IndexDatabase
from repomind.retrieval import ContextRetriever, fit_context_to_budget

AUDIT_SCHEMA_VERSION = "1"
MAX_RISK_FILE_BYTES = 500_000
RISK_LANGUAGES = frozenset({"python", "javascript", "jsx", "typescript", "tsx", "config", "sql"})
SECRET_LITERAL_RE = re.compile(
    r"""(?ix)
    \b(secret[_-]?key|jwt[_-]?secret|token|api[_-]?key|password)\b
    (?P<tail>\s*[:=]\s*)
    (?P<quote>["'])
    (?P<value>[^"']*)
    (?P=quote)
    """
)
GETENV_FALLBACK_RE = re.compile(
    r"""(?ix)
    getenv\(\s*["'](?:SECRET_KEY|JWT_SECRET|APP_SECRET)["']\s*,\s*
    (?P<quote>["'])(?P<value>[^"']*)(?P=quote)
    """
)
WEAK_SECRET_VALUES = frozenset(
    {
        "",
        "secret",
        "changeme",
        "change-me",
        "dev",
        "development",
        "test",
        "testing",
        "your-secret-key",
        "supersecret",
        "not-so-secret",
    }
)


def build_audit_report(database: IndexDatabase, task: str | None = None) -> dict[str, Any]:
    counts = database.counts()
    files = _files(database)
    languages = _group_counts(files, "language")
    purposes = _group_counts(files, "purpose")
    architecture = _architecture(database)
    routes = _routes(database)
    parse_errors = _parse_errors(database)
    test_files = [item["path"] for item in files if item["is_test"]][:20]
    important_files = _important_files(files)
    test_commands = _test_commands(database)
    risk_findings = _risk_findings(database, files, parse_errors, test_files, routes)
    context_task = task or "understand repository architecture, tests, API entry points, and risks"
    retriever = ContextRetriever(database)
    context_package = retriever.build_context(context_task, budget=1200, level=1)
    fitted_context, _ = fit_context_to_budget(
        context_package,
        lambda package: json.dumps(package, indent=2, sort_keys=False),
        1200,
    )
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "repomind_version": __version__,
        "repository": str(database.root),
        "summary": {
            "indexed_files": counts["files"],
            "symbols": counts["symbols"],
            "imports": counts["imports"],
            "dependencies": counts["dependencies"],
            "routes": counts["routes"],
            "parse_errors": len(parse_errors),
            "last_refresh": database.get_meta("last_refresh_at"),
        },
        "languages": languages,
        "purposes": purposes,
        "architecture": architecture,
        "important_files": important_files,
        "api_routes": routes,
        "test_files": test_files,
        "test_commands": test_commands,
        "risk_findings": risk_findings,
        "risk_notes": _risk_notes(files, parse_errors, test_files, routes, risk_findings),
        "parse_errors": parse_errors,
        "context_pack": {
            "task": context_task,
            "relevant_files": fitted_context.get("relevant_files", []),
            "important_symbols": fitted_context.get("important_symbols", []),
            "likely_modification_area": fitted_context.get("likely_modification_area", []),
        },
        "source_authority": "RepoMind audit reports guide discovery; inspect actual source before modification.",
    }


def render_audit_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# RepoMind Repository Audit",
        "",
        f"Repository: `{report['repository']}`",
        f"RepoMind version: `{report['repomind_version']}`",
        "",
        "## Summary",
    ]
    summary = report["summary"]
    lines.extend(
        [
            f"- Indexed files: {summary['indexed_files']}",
            f"- Symbols: {summary['symbols']}",
            f"- Imports: {summary['imports']}",
            f"- Dependencies: {summary['dependencies']}",
            f"- API routes: {summary['routes']}",
            f"- Parse errors: {summary['parse_errors']}",
        ]
    )
    _append_counts(lines, "Languages", report["languages"])
    _append_counts(lines, "File Purposes", report["purposes"])
    _append_records(
        lines,
        "Detected Architecture",
        report["architecture"],
        lambda item: f"{item['category']}: {item['name']} (evidence: `{item['evidence']}`)",
    )
    _append_records(
        lines,
        "Important Files",
        report["important_files"],
        lambda item: f"`{item['path']}` ({item['purpose']}, {item['language']}) - {item['reason']}",
    )
    _append_records(
        lines,
        "API Routes",
        report["api_routes"],
        lambda item: f"{item['method']} `{item['path']}` -> `{item['handler']}` in `{item['file']}`",
    )
    _append_records(lines, "Test Files", report["test_files"], lambda item: f"`{item}`")
    _append_records(lines, "Likely Test Commands", report["test_commands"], lambda item: f"`{item}`")
    _append_records(lines, "Risk Findings", report["risk_findings"], _render_risk_finding)
    _append_records(lines, "Risk Notes", report["risk_notes"], lambda item: str(item))
    _append_records(
        lines,
        "Suggested AI Context Pack",
        report["context_pack"]["relevant_files"],
        lambda item: f"`{item['path']}` ({item['purpose']}; score {item['score']})",
    )
    lines.extend(("", f"Source authority: {report['source_authority']}"))
    return "\n".join(lines).strip() + "\n"


def _files(database: IndexDatabase) -> list[dict[str, Any]]:
    return [
        {
            "id": int(row["id"]),
            "path": str(row["path"]),
            "language": str(row["language"]),
            "purpose": str(row["purpose"]),
            "is_test": bool(row["is_test"]),
            "parse_error": row["parse_error"],
        }
        for row in database.connection.execute(
            """SELECT id, path, language, purpose, is_test, parse_error
               FROM files ORDER BY path"""
        )
    ]


def _group_counts(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item[key])
        counts[value] = counts.get(value, 0) + 1
    return [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))
    ]


def _architecture(database: IndexDatabase) -> list[dict[str, Any]]:
    return [
        {
            "category": str(row["category"]),
            "name": str(row["name"]),
            "evidence": str(row["evidence"]),
            "confidence": float(row["confidence"]),
        }
        for row in database.connection.execute(
            "SELECT category, name, evidence, confidence FROM architecture ORDER BY category, name"
        )
    ]


def _routes(database: IndexDatabase) -> list[dict[str, Any]]:
    return [
        {
            "method": str(row["method"]),
            "path": str(row["path"]),
            "handler": str(row["handler"] or ""),
            "file": str(row["file"]),
            "line": int(row["line"]),
        }
        for row in database.connection.execute(
            """SELECT r.method, r.path, r.handler, r.line, f.path AS file
               FROM routes r JOIN files f ON f.id=r.file_id
               ORDER BY f.path, r.line LIMIT 50"""
        )
    ]


def _parse_errors(database: IndexDatabase) -> list[dict[str, str]]:
    return [
        {"path": str(row["path"]), "error": str(row["parse_error"])}
        for row in database.connection.execute(
            "SELECT path, parse_error FROM files WHERE parse_error IS NOT NULL ORDER BY path"
        )
    ]


def _important_files(files: list[dict[str, Any]]) -> list[dict[str, str]]:
    priority = {"api": 0, "source": 1, "test": 2, "configuration": 3, "migration": 4}
    selected = sorted(
        files,
        key=lambda item: (priority.get(str(item["purpose"]), 9), str(item["path"])),
    )[:20]
    return [
        {
            "path": str(item["path"]),
            "language": str(item["language"]),
            "purpose": str(item["purpose"]),
            "reason": _file_reason(str(item["purpose"])),
        }
        for item in selected
    ]


def _file_reason(purpose: str) -> str:
    reasons = {
        "api": "API or route-facing code",
        "source": "core source file",
        "test": "test coverage entry point",
        "configuration": "project configuration",
        "migration": "database or schema migration",
    }
    return reasons.get(purpose, "indexed repository file")


def _test_commands(database: IndexDatabase) -> list[str]:
    commands: list[str] = []
    architecture_names = {
        str(row["name"])
        for row in database.connection.execute("SELECT name FROM architecture WHERE category='testing'")
    }
    paths = {str(row["path"]) for row in database.connection.execute("SELECT path FROM files")}
    if "Pytest" in architecture_names or any(path.startswith("tests/") for path in paths):
        commands.append("python -m pytest")
    for path in sorted(path for path in paths if path.endswith("package.json")):
        commands.extend(_npm_script_commands(database.root / path))
    return sorted(dict.fromkeys(commands))


def _npm_script_commands(path: Path) -> list[str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    scripts = raw.get("scripts", {}) if isinstance(raw, dict) else {}
    if not isinstance(scripts, dict):
        return []
    commands: list[str] = []
    for script in ("test", "build", "lint"):
        if script in scripts:
            commands.append(f"npm run {script}")
    return commands


def _risk_findings(
    database: IndexDatabase,
    files: list[dict[str, Any]],
    parse_errors: list[dict[str, str]],
    test_files: list[str],
    routes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_files = _risk_source_files(database, files)
    findings: list[dict[str, Any]] = []
    _detect_sqlite_month_filter(findings, source_files)
    _detect_weak_secret_key(findings, source_files)
    _detect_unsafe_cors(findings, source_files)
    _detect_provisioning_token_exposure(findings, source_files)
    _detect_frontend_local_storage_token(findings, source_files)
    _detect_parent_provisioning_email_mismatch(findings, source_files)
    _detect_missing_frontend_flow_tests(findings, files, test_files, routes)
    if parse_errors:
        findings.append(
            _finding(
                "parse-errors",
                "medium",
                "analysis-coverage",
                "Parse errors can hide symbols, routes, and risk evidence.",
                f"{len(parse_errors)} indexed file(s) have parse errors.",
                [{"path": item["path"], "line": None, "snippet": item["error"]} for item in parse_errors],
                "Fix parser failures or reindex after upgrading RepoMind before relying on audit coverage.",
            )
        )
    return sorted(findings, key=lambda item: (_severity_rank(item["severity"]), item["id"]))


def _risk_source_files(
    database: IndexDatabase, files: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    source_files: list[dict[str, Any]] = []
    for item in files:
        if str(item["language"]) not in RISK_LANGUAGES:
            continue
        path = database.root / str(item["path"])
        try:
            if path.stat().st_size > MAX_RISK_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        source_files.append({**item, "text": text, "lower": text.lower(), "lines": lines})
    return source_files


def _detect_sqlite_month_filter(
    findings: list[dict[str, Any]], source_files: list[dict[str, Any]]
) -> None:
    evidence = _collect_evidence(source_files, lambda line: "func.strftime(" in line)
    if not evidence:
        return
    findings.append(
        _finding(
            "sqlite-month-filter",
            "high",
            "database-portability",
            "SQLite-only month filtering may fail or misbehave on PostgreSQL.",
            "SQLAlchemy `func.strftime(...)` is SQLite-specific; production PostgreSQL usually needs "
            "`date_trunc`, `extract`, or dialect-aware filtering.",
            evidence,
            "Replace SQLite-specific month filters with dialect-safe SQLAlchemy expressions and add "
            "database-backed tests for the production database.",
        )
    )


def _detect_weak_secret_key(
    findings: list[dict[str, Any]], source_files: list[dict[str, Any]]
) -> None:
    evidence: list[dict[str, Any]] = []
    for source in source_files:
        for line_number, line in enumerate(source["lines"], start=1):
            upper = line.upper()
            if "SECRET_KEY" not in upper and "JWT_SECRET" not in upper and "APP_SECRET" not in upper:
                continue
            literal = _literal_secret_value(line)
            if literal is None:
                continue
            if _is_weak_secret(literal):
                evidence.append(_evidence(source["path"], line_number, line))
    if not evidence:
        return
    findings.append(
        _finding(
            "weak-secret-key",
            "critical",
            "configuration-security",
            "Production secret key has a hard-coded or weak fallback.",
            "A weak `SECRET_KEY`/JWT secret can invalidate session, token, and signing guarantees.",
            evidence[:8],
            "Require a strong secret from the production environment and fail startup when it is "
            "missing, short, or set to a development placeholder.",
        )
    )


def _detect_unsafe_cors(
    findings: list[dict[str, Any]], source_files: list[dict[str, Any]]
) -> None:
    evidence = _collect_evidence(
        source_files,
        lambda line: (
            ("allow_origins" in line and '"*"' in line)
            or ("allow_origins" in line and "'*'" in line)
            or ("origin" in line.lower() and '"*"' in line and "cors" in line.lower())
            or ("origin" in line.lower() and "'*'" in line and "cors" in line.lower())
        ),
    )
    if not evidence:
        return
    findings.append(
        _finding(
            "unsafe-cors",
            "high",
            "configuration-security",
            "Wildcard CORS configuration is unsafe for production.",
            "Wildcard origins, especially near credentials or bearer tokens, can weaken browser-side "
            "trust boundaries.",
            evidence,
            "Use explicit environment-specific origins and keep credentialed CORS disabled unless "
            "the exact frontend origins are allowlisted.",
        )
    )


def _detect_provisioning_token_exposure(
    findings: list[dict[str, Any]], source_files: list[dict[str, Any]]
) -> None:
    keywords = ("activation_token", "provisioning_token", "invite_token", "inviteToken")
    evidence = _collect_evidence(
        source_files,
        lambda line: any(keyword in line for keyword in keywords)
        and any(marker in line.lower() for marker in ("return", "response", "copy", "manual", "admin")),
    )
    frontend_evidence = _collect_evidence(
        [source for source in source_files if "frontend/" in str(source["path"]).replace("\\", "/")],
        lambda line: any(keyword in line for keyword in keywords),
    )
    combined = [*evidence, *frontend_evidence]
    if not combined:
        return
    findings.append(
        _finding(
            "provisioning-token-exposure",
            "high",
            "token-handling",
            "Activation or provisioning tokens appear exposed through manual/admin flows.",
            "Provisioning tokens in API responses or frontend/admin screens are high-value secrets "
            "and can be copied, logged, or reused outside the intended channel.",
            _dedupe_evidence(combined)[:8],
            "Prefer one-time, short-lived delivery through controlled email or invite channels, and "
            "avoid returning raw provisioning tokens to general admin/front-end views.",
        )
    )


def _detect_frontend_local_storage_token(
    findings: list[dict[str, Any]], source_files: list[dict[str, Any]]
) -> None:
    frontend_sources = [
        source for source in source_files if "frontend/" in str(source["path"]).replace("\\", "/")
    ]
    evidence = _collect_evidence(
        frontend_sources,
        lambda line: "localstorage" in line.lower()
        and any(marker in line.lower() for marker in ("token", "authorization", "bearer")),
    )
    if not evidence:
        return
    findings.append(
        _finding(
            "frontend-localstorage-bearer-token",
            "high",
            "token-handling",
            "Frontend stores bearer-token material in localStorage.",
            "Bearer tokens in localStorage are exposed to injected JavaScript and browser extensions.",
            evidence,
            "Prefer HttpOnly secure cookies or a short-lived in-memory token pattern with refresh "
            "rotation and XSS hardening.",
        )
    )


def _detect_parent_provisioning_email_mismatch(
    findings: list[dict[str, Any]], source_files: list[dict[str, Any]]
) -> None:
    evidence = _collect_evidence(
        source_files,
        lambda line: (
            any(marker in line.lower() for marker in ("parent_email", "guardian_email"))
            and any(marker in line.lower() for marker in ("provision", "invite", "activation", "student"))
        ),
    )
    if not evidence:
        return
    findings.append(
        _finding(
            "parent-provisioning-email-mismatch",
            "medium",
            "account-provisioning",
            "Parent provisioning email fields need explicit mismatch validation.",
            "Parent invite/provisioning code references parent email fields near student or activation "
            "flow logic; this is a common place for wrong-recipient account setup.",
            evidence,
            "Validate that the invited parent email, created user email, and activation recipient "
            "match exactly, and add tests for mismatch/retry paths.",
        )
    )


def _detect_missing_frontend_flow_tests(
    findings: list[dict[str, Any]],
    files: list[dict[str, Any]],
    test_files: list[str],
    routes: list[dict[str, Any]],
) -> None:
    frontend_files = [
        item["path"] for item in files if str(item["path"]).replace("\\", "/").startswith("frontend/")
    ]
    if not frontend_files:
        return
    frontend_tests = [
        path
        for path in test_files
        if str(path).replace("\\", "/").startswith("frontend/")
        or any(marker in str(path).lower() for marker in ("playwright", "cypress", ".spec.", ".test."))
    ]
    if frontend_tests:
        return
    critical_route_paths = [
        route["path"]
        for route in routes
        if any(
            marker in str(route["path"]).lower()
            for marker in ("auth", "login", "fees", "payment", "parent", "student", "provision")
        )
    ]
    if not critical_route_paths:
        return
    findings.append(
        _finding(
            "missing-frontend-critical-flow-tests",
            "medium",
            "test-coverage",
            "Critical frontend flows lack indexed E2E or component coverage.",
            "Frontend files and critical API routes were detected, but no frontend test, Playwright, "
            "or Cypress coverage was indexed.",
            [
                {
                    "path": str(path),
                    "line": None,
                    "snippet": "critical route without indexed frontend flow coverage",
                }
                for path in critical_route_paths[:8]
            ],
            "Add component or E2E tests for login/auth, payment/fees, parent/student provisioning, "
            "and other role-critical browser flows.",
        )
    )


def _risk_notes(
    files: list[dict[str, Any]],
    parse_errors: list[dict[str, str]],
    test_files: list[str],
    routes: list[dict[str, Any]],
    risk_findings: list[dict[str, Any]],
) -> list[str]:
    notes: list[str] = []
    for finding in risk_findings:
        notes.append(f"[{finding['severity']}] {finding['title']}")
    if parse_errors:
        notes.append(f"{len(parse_errors)} file(s) have parse errors and may have incomplete symbols.")
    if not test_files:
        notes.append("No indexed test files were detected.")
    if routes and not test_files:
        notes.append("API routes exist, but no matching test files were indexed.")
    if len(files) > 200:
        notes.append("Repository is large enough that audit findings should be sampled and prioritized.")
    if not notes:
        notes.append("No high-signal structural risk notes detected from the index.")
    return notes


def _collect_evidence(
    source_files: list[dict[str, Any]],
    predicate: Callable[[str], bool],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for source in source_files:
        for line_number, line in enumerate(source["lines"], start=1):
            if predicate(line):
                evidence.append(_evidence(source["path"], line_number, line))
                break
    return evidence[:12]


def _evidence(path: str, line: int | None, snippet: str) -> dict[str, Any]:
    return {"path": path, "line": line, "snippet": _redact_sensitive_line(snippet.strip())}


def _finding(
    identifier: str,
    severity: str,
    category: str,
    title: str,
    detail: str,
    evidence: list[dict[str, Any]],
    recommendation: str,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "severity": severity,
        "category": category,
        "title": title,
        "detail": detail,
        "evidence": evidence,
        "recommendation": recommendation,
    }


def _severity_rank(severity: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(severity, 9)


def _literal_secret_value(line: str) -> str | None:
    fallback = GETENV_FALLBACK_RE.search(line)
    if fallback:
        return fallback.group("value")
    assignment = SECRET_LITERAL_RE.search(line)
    if assignment:
        return assignment.group("value")
    return None


def _is_weak_secret(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in WEAK_SECRET_VALUES or len(value.strip()) < 32


def _redact_sensitive_line(line: str) -> str:
    redacted = SECRET_LITERAL_RE.sub(lambda match: f"{match.group(1)}{match.group('tail')}<redacted>", line)
    return GETENV_FALLBACK_RE.sub('getenv("SECRET_KEY", <redacted>)', redacted)


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, int | None, str]] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        key = (str(item["path"]), item["line"], str(item["snippet"]))
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _render_risk_finding(item: dict[str, Any]) -> str:
    evidence = item.get("evidence", [])
    evidence_text = ""
    if evidence:
        first = evidence[0]
        line = f":{first['line']}" if first.get("line") is not None else ""
        evidence_text = f" Evidence: `{first['path']}{line}` - {first['snippet']}"
    return (
        f"[{item['severity']}] {item['title']} ({item['category']}). "
        f"{item['detail']} Recommendation: {item['recommendation']}{evidence_text}"
    )


def _append_counts(lines: list[str], title: str, items: list[dict[str, Any]]) -> None:
    lines.extend(("", f"## {title}"))
    if not items:
        lines.append("- none")
        return
    for item in items:
        lines.append(f"- {item['name']}: {item['count']}")


def _append_records(
    lines: list[str],
    title: str,
    items: list[Any],
    render_item: Callable[[Any], str],
) -> None:
    lines.extend(("", f"## {title}"))
    if not items:
        lines.append("- none")
        return
    for item in items:
        lines.append(f"- {render_item(item)}")
