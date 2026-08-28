from __future__ import annotations

from repomind.utils import tokenize

TASK_INTENTS = (
    "bug_fix",
    "feature",
    "refactor",
    "security",
    "test",
    "documentation",
    "architecture",
    "performance",
    "dependency_change",
    "api_change",
    "database_change",
    "unknown",
)

_INTENT_TERMS: dict[str, set[str]] = {
    "bug_fix": {
        "bug",
        "crash",
        "defect",
        "error",
        "exception",
        "fail",
        "failing",
        "fix",
        "issue",
        "regression",
    },
    "feature": {"add", "build", "create", "implement", "new", "support"},
    "refactor": {"cleanup", "decouple", "extract", "refactor", "reorganize", "rename"},
    "security": {"auth", "csrf", "encrypt", "permission", "secret", "security", "token", "xss"},
    "test": {"coverage", "spec", "test", "tests", "unit"},
    "documentation": {"doc", "docs", "documentation", "readme"},
    "architecture": {"architecture", "design", "module", "modules", "system"},
    "performance": {"benchmark", "latency", "memory", "optimize", "performance", "slow"},
    "dependency_change": {"dependency", "dependencies", "package", "upgrade", "version"},
    "api_change": {"api", "endpoint", "handler", "route", "routes"},
    "database_change": {"alembic", "database", "migration", "model", "schema", "sql", "table"},
}

_INTENT_PHRASES: dict[str, tuple[str, ...]] = {
    "bug_fix": ("fix ", "broken ", "not working"),
    "feature": ("add ", "new ", "implement "),
    "test": ("write tests", "add tests", "test "),
    "dependency_change": ("bump ", "upgrade ", "dependency "),
    "api_change": ("api endpoint", "add endpoint", "route "),
    "database_change": ("add migration", "database migration", "schema change"),
}


def classify_task_intent(task: str) -> list[str]:
    """Return deterministic broad task intents without external models."""
    lowered = f" {task.lower()} "
    terms = tokenize(task)
    intents: list[str] = []
    for intent, intent_terms in _INTENT_TERMS.items():
        phrases = _INTENT_PHRASES.get(intent, ())
        if terms & intent_terms or any(phrase in lowered for phrase in phrases):
            intents.append(intent)
    return intents or ["unknown"]
