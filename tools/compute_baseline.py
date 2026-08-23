import json
from pathlib import Path

from repomind.utils import approximate_tokens


def repo_tokens(root: Path) -> int:
    total_text = []
    for path in root.rglob("*"):
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            total_text.append(text)
    return approximate_tokens("\n".join(total_text))


if __name__ == "__main__":
    fixtures = [
        Path("tests/fixtures/realistic_a_backend"),
        Path("tests/fixtures/realistic_b_frontend"),
        Path("tests/fixtures/realistic_c_fullstack"),
    ]
    results = {}
    for f in fixtures:
        results[str(f)] = repo_tokens(f)
    print(json.dumps(results, indent=2))
