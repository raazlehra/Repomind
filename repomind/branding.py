"""Display branding and artifact-bound installation advice.

Distribution, import, CLI, MCP and storage identities remain ``repomind``.
"""

from __future__ import annotations

PRODUCT_NAME = "Lehraz Atlas Free"


def optional_installation_hint(extra: str) -> str:
    return (
        f"Install [{extra}] from a checksum-verified {PRODUCT_NAME} (formerly RepoMind) "
        "GitHub Release wheel. Follow "
        "https://github.com/raazlehra/Repomind/blob/main/docs/INSTALLATION.md"
        "#optional-dependencies. Do not resolve the unrelated repomind project from PyPI."
    )
