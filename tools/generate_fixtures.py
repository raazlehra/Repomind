"""Generate deterministic fixture repositories of varying size.

Usage:
    python -m tools.generate_fixtures --out tests/fixtures/large_fixture --count 200
"""
from __future__ import annotations

import argparse
import random
import textwrap
from pathlib import Path


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def make_noise_file(path: Path, idx: int) -> None:
    content = "\n".join([f"# noise file {idx}", "def f():", "    return None"]) + "\n"
    write_file(path, content)


def make_python_module(path: Path, name: str, imports: list[str] | None = None, body: str | None = None) -> None:
    imports = imports or []
    body = body or "def run():\n    return None\n"
    content = "\n".join([f"import {i}" for i in imports]) + "\n\n" + body
    write_file(path, content)


def generate_repo(root: Path, total_files: int, seed: int = 0) -> None:
    random.seed(seed)
    # Create some directories
    dirs = ["backend", "frontend/src/components", "frontend/src", "tests", "docs", "vendor"]
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)

    # Add primary cross-layer files
    write_file(root / "backend" / "routes.py", textwrap.dedent(
        """
        from .services import DashboardService


        def dashboard_endpoint(user_id: int):
            svc = DashboardService()
            return svc.get_dashboard(user_id)
        """
    ))
    write_file(root / "backend" / "services.py", textwrap.dedent(
        """
        from .models import DashboardModel


        class DashboardService:
            def get_dashboard(self, user_id: int) -> DashboardModel:
                return DashboardModel(total=42, active=10)
        """
    ))
    write_file(root / "backend" / "models.py", textwrap.dedent(
        """
        from dataclasses import dataclass


        @dataclass
        class DashboardModel:
            total: int
            active: int
        """
    ))
    write_file(root / "frontend" / "src" / "apiClient.ts", textwrap.dedent(
        """
        export async function getDashboard() {
          return { total: 0, active: 0 };
        }
        """
    ))
    write_file(root / "frontend" / "src" / "components" / "Dashboard.tsx", textwrap.dedent(
        """
        import { getDashboard } from "../apiClient";

        export default function Dashboard() {
          async function load() {
            const data = await getDashboard();
            console.log("dashboard", data);
          }
          return "Dashboard";
        }
        """
    ))

    # Fill remaining files with noise modules and some misleading files
    created = 6
    idx = 0
    while created < total_files:
        idx += 1
        # sometimes create tests, sometimes docs, sometimes vendor
        kind = random.choice(["py", "md", "ts", "py", "py"])
        if kind == "py":
            path = root / f"module_{idx}.py"
            make_noise_file(path, idx)
        elif kind == "md":
            write_file(root / "docs" / f"doc_{idx}.md", f"# Doc {idx}\nSome text about dashboard and auth\n")
        else:
            write_file(root / "frontend" / "src" / f"comp_{idx}.ts", "// noise ts file\n")
        created += 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.out.exists():
        # clear
        import shutil

        shutil.rmtree(args.out)
    args.out.mkdir(parents=True, exist_ok=True)
    generate_repo(args.out, args.count, seed=args.seed)


if __name__ == "__main__":
    main()
