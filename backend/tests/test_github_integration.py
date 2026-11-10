import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app.main as main

client = TestClient(main.app)


def test_github_repository_discovery_and_connection(monkeypatch) -> None:
    login = client.post(
        "/api/v1/auth/register",
        json={"name": "GitHub Test", "email": f"{uuid4()}@example.com", "password": "secure-password"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    before_connect = client.get("/api/v1/github/repositories", headers=headers)
    assert before_connect.status_code == 200
    assert before_connect.json() == []

    monkeypatch.setattr(main, "validate_github_token", lambda token: {"login": "test-account"})
    monkeypatch.setattr(
        main,
        "get_github_repositories",
        lambda token: [{
            "full_name": "octo-org/feature-service",
            "name": "feature-service",
            "default_branch": "main",
            "primary_language": "Python",
            "description": "Integration test repository",
        }],
    )
    saved = client.post("/api/v1/github/token", headers=headers, json={"token": "test-token-value"})
    assert saved.status_code == 200, saved.text

    repos = client.get("/api/v1/github/repositories", headers=headers)
    assert repos.status_code == 200, repos.text
    assert repos.json()[0]["full_name"] == "octo-org/feature-service"

    connected = client.post(
        "/api/v1/repositories/connect",
        headers=headers,
        json={
            "full_name": "octo-org/feature-service",
            "name": "feature-service",
            "default_branch": "main",
            "primary_language": "Python",
        },
    )
    assert connected.status_code == 200, connected.text
    monkeypatch.setattr(main, "repo_structure_for", lambda *args: ["README.md", "src/main.py"])
    structure = client.get(f"/api/v1/repositories/{connected.json()['id']}/structure", headers=headers)
    assert structure.status_code == 200, structure.text
    assert structure.json()["files"] == ["README.md", "src/main.py"]
