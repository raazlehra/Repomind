from __future__ import annotations

import json
from pathlib import Path

from repomind.cli import main


def test_cli_init_status_map_context_impact(python_repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["init", str(python_repo), "--format", "json"]) == 0
    init_data = json.loads(capsys.readouterr().out)
    assert init_data["indexed_files"] > 0

    assert main(["status", "-C", str(python_repo), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["index_healthy"] is True

    assert main(["map", "-C", str(python_repo), "--symbols", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["files"]

    assert (
        main(
            ["context", "fix login", "-C", str(python_repo), "--budget", "750", "--format", "json"]
        )
        == 0
    )
    context = json.loads(capsys.readouterr().out)
    assert context["relevant_files"]

    assert main(["impact", "AuthService.login", "-C", str(python_repo), "--format", "json"]) == 0
    assert "direct_dependents" in json.loads(capsys.readouterr().out)


def test_cli_not_indexed_error(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["status", "-C", str(tmp_path)]) == 2
    assert "Repository is not indexed. Run: repomind init" in capsys.readouterr().err


def test_cli_audit_writes_markdown_and_json(python_repo: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    markdown_path = tmp_path / "audit.md"
    json_path = tmp_path / "audit.json"

    assert (
        main(
            [
                "audit",
                str(python_repo),
                "--task",
                "fix authentication route",
                "--output",
                str(markdown_path),
                "--json",
                str(json_path),
            ]
        )
        == 0
    )
    status = capsys.readouterr().out
    assert "Audit: written" in status
    markdown = markdown_path.read_text(encoding="utf-8")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert markdown_path.stat().st_size > 0
    assert json_path.stat().st_size > 0
    assert "# RepoMind Repository Audit" in markdown
    assert "POST `/login`" in markdown
    assert data["summary"]["parse_errors"] == 0
    assert data["summary"]["routes"] >= 2
    assert any(route["path"] == "/login" for route in data["api_routes"])
    assert data["context_pack"]["relevant_files"]
    assert "python -m pytest" in data["test_commands"]


def test_cli_audit_detects_package_scripts(mixed_repo: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    json_path = tmp_path / "mixed-audit.json"

    assert main(["audit", str(mixed_repo), "--json", str(json_path), "--output", str(tmp_path / "audit.md")]) == 0
    capsys.readouterr()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "npm run build" in data["test_commands"]
    assert "npm run test" in data["test_commands"]
    assert any(item["name"] == "React" for item in data["architecture"])
    assert any(item["name"] == "FastAPI" for item in data["architecture"])


def test_cli_audit_detects_paid_audit_risks(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "risky_app"
    (repo / "backend" / "app" / "api").mkdir(parents=True)
    (repo / "frontend" / "src").mkdir(parents=True)
    (repo / "backend" / "tests").mkdir(parents=True)
    (repo / "reports").mkdir(parents=True)
    (repo / "backend" / "requirements.txt").write_text(
        "fastapi\nsqlalchemy\npsycopg2\npytest\n",
        encoding="utf-8",
    )
    (repo / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"@vitejs/plugin-react": "latest", "react": "latest"},
                "devDependencies": {"typescript": "latest", "vite": "latest"},
                "scripts": {"build": "vite build"},
            }
        ),
        encoding="utf-8",
    )
    (repo / "backend" / "app" / "main.py").write_text(
        """from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)
""",
        encoding="utf-8",
    )
    (repo / "backend" / "app" / "config.py").write_text(
        """import os

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
""",
        encoding="utf-8",
    )
    (repo / "backend" / "app" / "api" / "reports.py").write_text(
        """from fastapi import APIRouter
from sqlalchemy import func

router = APIRouter()

@router.get("/fees/monthly")
def monthly_fees():
    return func.strftime("%Y-%m", "created_at")
""",
        encoding="utf-8",
    )
    (repo / "backend" / "app" / "api" / "parents.py").write_text(
        """from fastapi import APIRouter

router = APIRouter()

@router.post("/parents/provision")
def provision_parent(parent_email: str):
    invite = {"activation_token": "token-value", "parent_email": parent_email}
    return {"activation_token": invite["activation_token"], "parent_email": parent_email}
""",
        encoding="utf-8",
    )
    (repo / "frontend" / "src" / "auth.ts").write_text(
        """export function saveToken(token: string) {
  localStorage.setItem("auth_token", token);
  return { Authorization: `Bearer ${localStorage.getItem("auth_token")}` };
}
""",
        encoding="utf-8",
    )
    (repo / "frontend" / "src" / "AdminProvisioning.tsx").write_text(
        """export function AdminProvisioning({ activation_token }: { activation_token: string }) {
  return <textarea value={activation_token} readOnly />;
}
""",
        encoding="utf-8",
    )
    (repo / "backend" / "tests" / "test_parents.py").write_text(
        "def test_backend_parent_flow() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    (repo / "reports" / "old-audit.json").write_text(
        json.dumps({"snippet": "parent_email provisioning activation_token"}),
        encoding="utf-8",
    )
    markdown_path = tmp_path / "risk-audit.md"
    json_path = tmp_path / "risk-audit.json"

    assert (
        main(
            [
                "audit",
                str(repo),
                "--output",
                str(markdown_path),
                "--json",
                str(json_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    markdown = markdown_path.read_text(encoding="utf-8")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    risk_ids = {finding["id"] for finding in data["risk_findings"]}
    assert {
        "sqlite-month-filter",
        "weak-secret-key",
        "unsafe-cors",
        "provisioning-token-exposure",
        "frontend-localstorage-bearer-token",
        "parent-provisioning-email-mismatch",
        "missing-frontend-critical-flow-tests",
    } <= risk_ids
    assert "Risk Findings" in markdown
    assert "SQLite-only month filtering" in markdown
    assert "Frontend stores bearer-token material in localStorage" in markdown
    assert "dev-secret" not in markdown
    weak_secret = next(finding for finding in data["risk_findings"] if finding["id"] == "weak-secret-key")
    assert weak_secret["evidence"][0]["path"] == "backend/app/config.py"
    assert any("redacted" in item["snippet"] for item in weak_secret["evidence"])
    parent_email = next(
        finding
        for finding in data["risk_findings"]
        if finding["id"] == "parent-provisioning-email-mismatch"
    )
    assert parent_email["evidence"][0]["path"] == "backend/app/api/parents.py"
    assert all(not item["path"].startswith("frontend/") for item in parent_email["evidence"])
    assert all(not item["path"].startswith("reports/") for item in parent_email["evidence"])


def test_cli_audit_frontend_guardian_email_payload_alone_is_not_parent_mismatch_risk(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "frontend_only_guardian_email"
    (repo / "frontend" / "src").mkdir(parents=True)
    (repo / "frontend" / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"react": "latest"},
                "devDependencies": {"typescript": "latest", "vite": "latest"},
                "scripts": {"build": "vite build"},
            }
        ),
        encoding="utf-8",
    )
    (repo / "frontend" / "src" / "students.tsx").write_text(
        """export function saveStudent(form: { guardian_email: string }) {
  return fetch("/api/students", {
    method: "POST",
    body: JSON.stringify({
      guardian_email: undefined,
      parent: { email: form.guardian_email || undefined },
    }),
  });
}
""",
        encoding="utf-8",
    )
    json_path = tmp_path / "frontend-only-audit.json"

    assert main(["audit", str(repo), "--json", str(json_path), "--output", str(tmp_path / "audit.md")]) == 0
    capsys.readouterr()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    risk_ids = {finding["id"] for finding in data["risk_findings"]}
    assert "parent-provisioning-email-mismatch" not in risk_ids


def test_cli_audit_parent_mismatch_validation_suppresses_parent_email_risk(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "validated_parent_provisioning"
    (repo / "backend" / "app" / "services").mkdir(parents=True)
    (repo / "backend" / "tests").mkdir(parents=True)
    (repo / "backend" / "app" / "services" / "provisioning.py").write_text(
        """from fastapi import HTTPException

def provision_account(entity_type: str, entity, email: str):
    if entity_type == "parent":
        if not entity.email:
            raise HTTPException(status_code=422, detail="Parent record must have a guardian email before account provisioning")
        if email != entity.email:
            raise HTTPException(status_code=422, detail="Parent account email must match the guardian email on the parent record")
    return {"email": email, "manual_invitation_token": "token"}
""",
        encoding="utf-8",
    )
    (repo / "backend" / "tests" / "test_parent_provisioning.py").write_text(
        """def test_parent_provisioning_rejects_email_mismatch(client):
    mismatch = client.post("/api/users/provision-parent", json={"parent_id": 1, "email": "child@example.com"})
    assert mismatch.status_code == 422
""",
        encoding="utf-8",
    )
    json_path = tmp_path / "validated-parent-audit.json"

    assert main(["audit", str(repo), "--json", str(json_path), "--output", str(tmp_path / "audit.md")]) == 0
    capsys.readouterr()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    risk_ids = {finding["id"] for finding in data["risk_findings"]}
    assert "parent-provisioning-email-mismatch" not in risk_ids


def test_cli_audit_does_not_report_test_secret_values_as_runtime_risk(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "validated_config_app"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / "backend" / "tests").mkdir(parents=True)
    (repo / "backend" / "app" / "config.py").write_text(
        """import os

SECRET_KEY = os.environ["SECRET_KEY"]

def validate_for_runtime() -> None:
    if len(SECRET_KEY) < 32:
        raise RuntimeError("SECRET_KEY is too short")
""",
        encoding="utf-8",
    )
    (repo / "backend" / "tests" / "test_config.py").write_text(
        """from backend.app.config import validate_for_runtime

def valid_production_settings(secret_key: str) -> object:
    return object()

def test_rejects_weak_secret_key() -> None:
    settings = valid_production_settings(secret_key="dev-secret")
    assert settings is not None
    validate_for_runtime
""",
        encoding="utf-8",
    )
    markdown_path = tmp_path / "validated-config-audit.md"
    json_path = tmp_path / "validated-config-audit.json"

    assert (
        main(
            [
                "audit",
                str(repo),
                "--output",
                str(markdown_path),
                "--json",
                str(json_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    weak_secret_findings = [
        finding for finding in data["risk_findings"] if finding["id"] == "weak-secret-key"
    ]
    assert weak_secret_findings == []
    assert markdown_path.stat().st_size > 0
    assert json_path.stat().st_size > 0


def test_cli_install_codex_is_idempotent(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["install-codex", str(tmp_path), "--format", "json"]) == 0
    capsys.readouterr()
    assert main(["install-codex", str(tmp_path), "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["agents"]["action"] == "unchanged"
