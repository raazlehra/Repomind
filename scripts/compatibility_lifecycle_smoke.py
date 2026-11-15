"""Download and authenticate the frozen b13 baseline, then qualify a candidate."""

from __future__ import annotations

import argparse
import json
import tempfile
import urllib.request
from pathlib import Path

from release_lifecycle_smoke import execute

BASELINE_VERSION = "2.0.0b13"
BASELINE_SHA256 = "6152d1fa9761dd55662defe68a77d02cd50e7dd22bc4c013f62a1b7080601bd9"
BASELINE_FILENAME = "repomind-2.0.0b13-py3-none-any.whl"
BASELINE_URL = (
    "https://github.com/raazlehra/Repomind/releases/download/v2.0.0b13/" + BASELINE_FILENAME
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-wheel", type=Path, required=True)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--baseline-wheel", type=Path, help="use an existing authenticated download")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="lehraz atlas upgrade gate ") as temporary:
        root = Path(temporary)
        baseline = args.baseline_wheel.resolve() if args.baseline_wheel else root / BASELINE_FILENAME
        if not args.baseline_wheel:
            with urllib.request.urlopen(BASELINE_URL, timeout=60) as response:
                baseline.write_bytes(response.read())
        result = execute(
            baseline, args.candidate_wheel.resolve(), root, baseline_version=BASELINE_VERSION,
            candidate_version=args.candidate_version, baseline_sha256=BASELINE_SHA256,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
