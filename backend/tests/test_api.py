import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app.main as main
from app.database import SessionLocal
from app.llm_service import AgentOutput
from app.models import EventLog, Repository, Task, User, UserCredential
from app.github_service import save_user_github_token

client = TestClient(main.app)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login() -> str:
    response = client.post("/api/v1/auth/login", json={"email": "demo@ase.dev", "password": "password123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def create_task(token: str, **overrides: str) -> tuple[str, str]:
    headers = auth_headers(token)
    repositories = client.get("/api/v1/repositories", headers=headers)
    assert repositories.status_code == 200, repositories.text
    repository_list = repositories.json()
    if not repository_list:
        connected = client.post(
            "/api/v1/repositories",
            headers=headers,
            json={
                "full_name": "octo-org/ase-demo",
                "name": "ase-demo",
                "default_branch": "main",
                "primary_language": "Python",
            },
        )
        assert connected.status_code == 200, connected.text
        repository_list = [connected.json()]
    repository_id = repository_list[0]["id"]
    response = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "repository_id": repository_id,
            "title": overrides.get("title", "Implement an integration feature"),
            "description": overrides.get("description", "Implement the requested change with focused tests."),
            "priority": "medium",
            "base_branch": "main",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"], repository_id


def set_task_state(task_id: str, **values: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).one()
        for key, value in values.items():
            setattr(task, key, value)
        db.commit()
    finally:
        db.close()


def test_health_and_login() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    token = login()
    dashboard = client.get("/api/v1/dashboard", headers=auth_headers(token))
    assert dashboard.status_code == 200
    assert dashboard.json()["total_tasks"] >= 0


def test_registration_rejects_an_existing_email() -> None:
    user = {"name": "Duplicate Test", "email": f"{uuid4()}@example.com", "password": "secure-password"}

    first_registration = client.post("/api/v1/auth/register", json=user)
    assert first_registration.status_code == 200, first_registration.text

    duplicate_registration = client.post("/api/v1/auth/register", json=user)
    assert duplicate_registration.status_code == 400
    assert duplicate_registration.json()["detail"] == "Email already registered"


def test_llm_config_reports_groq_status(monkeypatch) -> None:
    monkeypatch.setattr(main, "groq_configured", lambda: True)
    monkeypatch.setattr(main, "groq_model", lambda: "test-model")

    response = client.get("/api/v1/llm/config", headers=auth_headers(login()))

    assert response.status_code == 200, response.text
    assert response.json() == {"configured": True, "provider": "groq", "model": "test-model"}


def test_task_starts_without_a_fabricated_diff() -> None:
    token = login()
    task_id, _ = create_task(token)

    diff = client.get(f"/api/v1/tasks/{task_id}/diff", headers=auth_headers(token))
    assert diff.status_code == 200
    assert diff.json()["diff"] == ""

    approval = client.post(f"/api/v1/tasks/{task_id}/approve", headers=auth_headers(token))
    assert approval.status_code == 409


def test_groq_agents_advance_and_save_the_patch(monkeypatch) -> None:
    token = login()
    task_id, _ = create_task(token)
    headers = auth_headers(token)
    monkeypatch.setattr(main, "get_user_github_token", lambda db, user_id: "github-test-token")
    monkeypatch.setattr(main, "get_repository_context", lambda *args, **kwargs: "--- README.md ---\nProject")
    monkeypatch.setattr(
        main,
        "build_patch_from_edits",
        lambda *args: "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-Project\n+Updated project\n",
    )
    monkeypatch.setattr(main, "check_patch_applies", lambda *args: None)
    outputs = {
        "repository_analyzer": "Repository summary and relevant files.",
        "planner": "1. Update README.md. 2. Run tests.",
        "coder": '{"files":[{"path":"README.md","action":"edit","edits":[{"search":"Project","replace":"Updated project"}]}]}',
    }
    monkeypatch.setattr(main, "generate_agent_output", lambda agent, *args: outputs[agent])

    client.post(f"/api/v1/tasks/{task_id}/start", headers=headers)
    for next_agent in ("planner", "coder", "validator"):
        response = client.post(f"/api/v1/tasks/{task_id}/workflow/run", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["current_agent"] == next_agent

    diff = client.get(f"/api/v1/tasks/{task_id}/diff", headers=headers)
    assert "Updated project" in diff.json()["diff"]


def test_coder_repairs_patch_rejected_by_git_apply(monkeypatch) -> None:
    token = login()
    task_id, _ = create_task(token)
    set_task_state(task_id, status="coding", current_agent="coder")
    monkeypatch.setattr(main, "get_user_github_token", lambda db, user_id: "github-test-token")
    monkeypatch.setattr(main, "get_repository_context", lambda *args, **kwargs: "repository context")
    outputs = [
        '{"files":[{"path":"main.cpp","action":"create","content":"first"}]}',
        '{"files":[{"path":"main.cpp","action":"create","content":"second"}]}',
        '{"files":[{"path":"main.cpp","action":"create","content":"third"}]}',
    ]
    generation_args: list[tuple] = []

    def generate(agent, *args):
        generation_args.append(args)
        return outputs.pop(0)

    patches = iter([
        "--- /dev/null\n+++ b/main.cpp\n@@ -0,0 +1 @@\n+first\n",
        "--- /dev/null\n+++ b/main.cpp\n@@ -0,0 +1 @@\n+second\n",
        "--- /dev/null\n+++ b/main.cpp\n@@ -0,0 +1 @@\n+third\n",
    ])
    checks = iter(["error: corrupt patch at line 5", "error: corrupt patch at line 5", None])
    monkeypatch.setattr(main, "generate_agent_output", generate)
    monkeypatch.setattr(main, "build_patch_from_edits", lambda *args: next(patches))
    monkeypatch.setattr(main, "check_patch_applies", lambda *args: next(checks))

    response = client.post(
        f"/api/v1/tasks/{task_id}/workflow/run",
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text
    assert len(generation_args) == 3
    assert generation_args[1][2].startswith("STRUCTURED EDIT VALIDATION FAILURE - FIX THIS FIRST.")
    assert "corrupt patch at line 5" in generation_args[1][2]
    assert "search/replace blocks" in generation_args[2][2]
    diff = client.get(f"/api/v1/tasks/{task_id}/diff", headers=auth_headers(token))
    assert "+third" in diff.json()["diff"]


def test_failed_coder_logs_all_rejected_groq_patches(monkeypatch) -> None:
    token = login()
    task_id, _ = create_task(token)
    set_task_state(task_id, status="coding", current_agent="coder")
    monkeypatch.setattr(main, "get_user_github_token", lambda db, user_id: "github-test-token")
    monkeypatch.setattr(main, "get_repository_context", lambda *args, **kwargs: "repository context")
    patches = [
        f"--- /dev/null\n+++ b/main.cpp\n@@ -0,0 +1 @@\n+attempt {attempt}\n"
        for attempt in range(1, 4)
    ]
    monkeypatch.setattr(main, "generate_agent_output", lambda *args: patches.pop(0))
    monkeypatch.setattr(
        main,
        "build_patch_from_edits",
        lambda *args: "--- /dev/null\n+++ b/main.cpp\n@@ -0,0 +1 @@\n+content\n",
    )
    monkeypatch.setattr(main, "check_patch_applies", lambda *args: "error: corrupt patch at line 15")

    response = client.post(
        f"/api/v1/tasks/{task_id}/workflow/run",
        headers=auth_headers(token),
    )

    assert response.status_code == 502
    logs = client.get(f"/api/v1/tasks/{task_id}/logs", headers=auth_headers(token))
    failed_event = next(event for event in logs.json()["events"] if event["event"] == "agent_failed")
    attempts = failed_event["payload"]["patch_attempts"]
    assert len(attempts) == 3
    assert [attempt["attempt"] for attempt in attempts] == [1, 2, 3]
    assert attempts[0]["patch"].endswith("+attempt 1\n")
    assert all(attempt["error"] == "error: corrupt patch at line 15" for attempt in attempts)


def test_coder_format_error_logs_raw_groq_responses(monkeypatch) -> None:
    token = login()
    task_id, _ = create_task(token)
    set_task_state(task_id, status="coding", current_agent="coder")
    monkeypatch.setattr(main, "get_user_github_token", lambda db, user_id: "github-test-token")
    monkeypatch.setattr(main, "get_repository_context", lambda *args, **kwargs: "repository context")
    invalid_patch = "--- /dev/null\n+++ b/main.py\n@@ -0,0 +1 @@\n+print('hi')\ninvalid line\n"
    monkeypatch.setattr(
        main,
        "generate_agent_output",
        lambda *args: (_ for _ in ()).throw(main.LLMProviderError(
            "Groq could not produce valid structured file edits: Invalid JSON.",
            output=invalid_patch,
            diagnostics="Unexpected line outside a diff hunk at line 5.",
            outputs=[invalid_patch, invalid_patch],
        )),
    )

    response = client.post(
        f"/api/v1/tasks/{task_id}/workflow/run",
        headers=auth_headers(token),
    )

    assert response.status_code == 502
    logs = client.get(f"/api/v1/tasks/{task_id}/logs", headers=auth_headers(token))
    failed_event = next(event for event in logs.json()["events"] if event["event"] == "agent_failed")
    assert failed_event["payload"]["patch_attempts"][0]["patch"] == invalid_patch
    assert failed_event["payload"]["patch_attempts"][1]["error"].startswith("Unexpected line")


def test_completed_coder_logs_model_edits_and_completion_metadata(monkeypatch) -> None:
    token = login()
    task_id, _ = create_task(token)
    set_task_state(task_id, status="coding", current_agent="coder")
    monkeypatch.setattr(main, "get_user_github_token", lambda db, user_id: "github-test-token")
    monkeypatch.setattr(main, "get_repository_context", lambda *args, **kwargs: "repository context")
    model_output = '{"files":[{"path":"README.md","action":"edit","edits":[]}]}'
    generated = AgentOutput(
        model_output,
        [{"finish_reason": "stop", "usage": {"prompt_tokens": 10, "completion_tokens": 20}}],
        raw_output="```json\n" + model_output + "\n```",
    )
    monkeypatch.setattr(main, "generate_agent_output", lambda *args: generated)
    monkeypatch.setattr(
        main,
        "build_patch_from_edits",
        lambda *args: "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n",
    )
    monkeypatch.setattr(main, "check_patch_applies", lambda *args: None)

    response = client.post(
        f"/api/v1/tasks/{task_id}/workflow/run",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    logs = client.get(f"/api/v1/tasks/{task_id}/logs", headers=auth_headers(token))
    completed_event = next(
        event
        for event in logs.json()["events"]
        if event["event"] == "agent_completed" and event["payload"].get("agent") == "coder"
    )
    assert completed_event["payload"]["model_output"] == "```json\n" + model_output + "\n```"
    assert completed_event["payload"]["completion_metadata"][0]["usage"]["completion_tokens"] == 20


def test_coding_stage_requires_groq_generation(monkeypatch) -> None:
    token = login()
    task_id, _ = create_task(token)
    set_task_state(
        task_id,
        title="Python program",
        description="Addition of two number",
        status="coding",
        current_agent="coder",
    )
    monkeypatch.setattr(main, "get_user_github_token", lambda db, user_id: "github-test-token")
    monkeypatch.setattr(main, "get_repository_context", lambda *args, **kwargs: "repository context")
    monkeypatch.setattr(
        main,
        "generate_agent_output",
        lambda *args: (_ for _ in ()).throw(main.LLMConfigurationError("Set GROQ_API_KEY.")),
    )

    response = client.post(
        f"/api/v1/tasks/{task_id}/workflow/run",
        headers=auth_headers(token),
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "Set GROQ_API_KEY."


def test_skip_validation_is_explicit_and_never_reported_as_passed() -> None:
    token = login()
    task_id, _ = create_task(token)
    set_task_state(
        task_id,
        diff="--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n",
        status="testing",
        current_agent="validator",
    )
    headers = auth_headers(token)

    skipped = client.post(f"/api/v1/tasks/{task_id}/skip-validation", headers=headers)
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["status"] == "skipped"

    logs = client.get(f"/api/v1/tasks/{task_id}/logs", headers=headers)
    skip_event = next(event for event in logs.json()["events"] if event["event"] == "validation_skipped")
    assert skip_event["payload"]["skipped"] is True
    assert skip_event["payload"]["success"] is False

    approval_without_review = client.post(f"/api/v1/tasks/{task_id}/approve", headers=headers)
    assert approval_without_review.status_code == 409

    db = SessionLocal()
    try:
        db.add(EventLog(
            task_id=task_id,
            event_type="agent_completed",
            message="reviewed",
            payload=json.dumps({"agent": "reviewer", "retry_count": 0, "result": "Review complete."}),
        ))
        db.commit()
    finally:
        db.close()
    approved = client.post(f"/api/v1/tasks/{task_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text


def test_workflow_reports_missing_groq_configuration(monkeypatch) -> None:
    token = login()
    task_id, _ = create_task(token)
    monkeypatch.setattr(main, "get_user_github_token", lambda db, user_id: "github-test-token")
    monkeypatch.setattr(main, "get_repository_context", lambda *args, **kwargs: "repository context")
    monkeypatch.setattr(
        main,
        "generate_agent_output",
        lambda *args: (_ for _ in ()).throw(main.LLMConfigurationError("Set GROQ_API_KEY.")),
    )
    response = client.post(f"/api/v1/tasks/{task_id}/workflow/run", headers=auth_headers(token))
    assert response.status_code == 503
    assert response.json()["detail"] == "Set GROQ_API_KEY."


def test_validation_applies_patch_and_uses_container_runner(monkeypatch, tmp_path) -> None:
    token = login()
    task_id, _ = create_task(token)
    patch = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-before\n+after\n"
    set_task_state(task_id, diff=patch, status="testing", current_agent="validator")
    workspace = tmp_path / ".workspaces"
    monkeypatch.setattr(main, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(main, "get_user_github_token", lambda db, user_id: "github-test-token")

    def fake_download(full_name, branch, github_token, destination):
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "README.md").write_text("before\n", encoding="utf-8")
        return destination

    monkeypatch.setattr(main, "download_repository", fake_download)
    observed: dict[str, str] = {}

    def fake_runner(task_id, command, *, cwd, timeout_seconds):
        observed["command"] = command
        observed["cwd"] = str(cwd)
        assert (Path(cwd) / "README.md").read_text(encoding="utf-8") == "after\n"
        return {
            "task_id": task_id,
            "command": command,
            "exit_code": 0,
            "success": True,
            "stdout": "tests passed",
            "stderr": "",
            "duration_ms": 10,
            "working_directory": str(cwd),
            "created_at": "2026-01-01T00:00:00",
        }

    monkeypatch.setattr(main, "run_local_command", fake_runner)
    result = client.post(f"/api/v1/tasks/{task_id}/execute", headers=auth_headers(token), json={"command": "python --version"})
    assert result.status_code == 200, result.text
    assert result.json()["success"] is True
    assert observed["cwd"].startswith(str(workspace))
    assert observed["command"] == "python --version"


def test_validation_generates_temporary_tests_when_pytest_collects_none(monkeypatch, tmp_path) -> None:
    token = login()
    task_id, _ = create_task(token)
    patch = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-before\n+after\n"
    set_task_state(task_id, diff=patch, status="testing", current_agent="validator")
    workspace = tmp_path / ".workspaces"
    monkeypatch.setattr(main, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(main, "get_user_github_token", lambda db, user_id: "github-test-token")

    def fake_download(full_name, branch, github_token, destination):
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "README.md").write_text("before\n", encoding="utf-8")
        (destination / "module.py").write_text("def add(left, right):\n    return left + right\n", encoding="utf-8")
        return destination

    monkeypatch.setattr(main, "download_repository", fake_download)
    monkeypatch.setattr(main, "generate_validation_tests", lambda *args: "def test_add():\n    assert 1 + 1 == 2\n")
    runs: list[tuple[str, bool]] = []

    def fake_runner(task_id, command, *, cwd, timeout_seconds):
        generated_files = list(Path(cwd).glob("test_ase_generated_*.py"))
        runs.append((command, bool(generated_files)))
        if len(runs) == 1:
            return {
                "task_id": task_id,
                "command": command,
                "exit_code": 5,
                "success": False,
                "stdout": "no tests ran",
                "stderr": "",
                "duration_ms": 10,
                "working_directory": str(cwd),
                "created_at": "2026-01-01T00:00:00",
            }
        assert len(generated_files) == 1
        assert "def test_add" in generated_files[0].read_text(encoding="utf-8")
        return {
            "task_id": task_id,
            "command": command,
            "exit_code": 0,
            "success": True,
            "stdout": "1 passed",
            "stderr": "",
            "duration_ms": 10,
            "working_directory": str(cwd),
            "created_at": "2026-01-01T00:00:00",
        }

    monkeypatch.setattr(main, "run_local_command", fake_runner)
    response = client.post(
        f"/api/v1/tasks/{task_id}/execute",
        headers=auth_headers(token),
        json={"command": "python -m pytest -q"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    assert "Groq generated temporary pytest tests" in response.json()["stdout"]
    assert "test_ase_generated_" in runs[1][0]
    assert runs[0] == ("python -m pytest -q", False)
    assert runs[1][1] is True
    assert list(workspace.rglob("test_ase_generated_*.py")) == []
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).one()
        assert task.diff == patch
    finally:
        db.close()


def test_invalid_patch_fails_task_so_it_can_be_retried(monkeypatch, tmp_path) -> None:
    token = login()
    task_id, _ = create_task(token)
    patch = (
        "--- /dev/null\n+++ b/main.cpp\n@@ -0,0 +1,5 @@\n"
        "+#include <iostream>\n+int main() {\n"
    )
    set_task_state(task_id, diff=patch, status="testing", current_agent="validator")
    monkeypatch.setattr(main, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(main, "get_user_github_token", lambda db, user_id: "github-test-token")

    def fake_download(full_name, branch, github_token, destination):
        destination.mkdir(parents=True, exist_ok=True)
        return destination

    monkeypatch.setattr(main, "download_repository", fake_download)
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, stdout="", stderr="error: corrupt patch at line 5"),
    )

    response = client.post(
        f"/api/v1/tasks/{task_id}/execute",
        headers=auth_headers(token),
        json={"command": "python --version"},
    )

    assert response.status_code == 422
    assert "corrupt patch at line 5" in response.json()["detail"]
    retry = client.post(f"/api/v1/tasks/{task_id}/retry", headers=auth_headers(token))
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "queued"


def test_github_token_is_verified_and_encrypted(monkeypatch) -> None:
    token = login()
    monkeypatch.setattr(main, "validate_github_token", lambda value: {"login": "test-account"})
    monkeypatch.setattr(main, "get_github_repositories", lambda value: [{"full_name": "owner/repo"}])
    response = client.post(
        "/api/v1/github/token",
        headers=auth_headers(token),
        json={"token": "ghp_a-realistic-test-secret"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["account"] == "test-account"
    assert "token" not in response.json()

    configuration = client.get("/api/v1/github/config", headers=auth_headers(token))
    assert configuration.json()["configured"] is True
    repositories = client.get("/api/v1/github/repositories", headers=auth_headers(token))
    assert repositories.json() == [{"full_name": "owner/repo"}]

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@ase.dev").one()
        credential = db.query(UserCredential).filter(UserCredential.user_id == user.id).one()
        assert "ghp_a-realistic-test-secret" not in credential.encrypted_token
    finally:
        db.close()


def test_pull_request_requires_approval_and_publishes_real_remote_result(monkeypatch, tmp_path) -> None:
    token = login()
    task_id, repository_id = create_task(token)
    headers = auth_headers(token)
    patch = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-before\n+after\n"
    set_task_state(task_id, diff=patch, status="reviewing", current_agent="reviewer")
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).one()
        user = db.query(User).filter(User.id == task.user_id).one()
        save_user_github_token(db, user.id, "test-github-token")
        db.add(EventLog(task_id=task_id, event_type="validation_completed", message="passed", payload=json.dumps({"success": True})))
        db.add(EventLog(task_id=task_id, event_type="agent_completed", message="reviewed", payload=json.dumps({"agent": "reviewer", "result": "Ready"})))
        db.commit()
    finally:
        db.close()

    gated = client.post(
        f"/api/v1/tasks/{task_id}/pull-request",
        headers=headers,
        json={"title": "Task patch", "head_branch": "feature/task-patch", "base_branch": "main"},
    )
    assert gated.status_code == 409

    approved = client.post(f"/api/v1/tasks/{task_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text

    monkeypatch.setattr(main, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(main, "publish_patch_as_branch", lambda *args, **kwargs: "commit-sha")
    monkeypatch.setattr(
        main,
        "create_github_pull_request",
        lambda *args, **kwargs: {"number": 12, "html_url": "https://github.com/owner/repo/pull/12", "state": "open"},
    )
    created = client.post(
        f"/api/v1/tasks/{task_id}/pull-request",
        headers=headers,
        json={"title": "Task patch", "head_branch": "feature/task-patch", "base_branch": "main"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["url"] == "https://github.com/owner/repo/pull/12"
    assert created.json()["status"] == "draft"


def test_task_events_are_scoped_to_the_owner() -> None:
    token = login()
    task_id, _ = create_task(token)
    registered = client.post(
        "/api/v1/auth/register",
        json={"name": "Other User", "email": f"{uuid4()}@example.com", "password": "secure-password"},
    )
    assert registered.status_code == 200, registered.text
    other_token = registered.json()["access_token"]

    response = client.get(f"/api/v1/tasks/{task_id}/events", headers=auth_headers(other_token))
    assert response.status_code == 404
