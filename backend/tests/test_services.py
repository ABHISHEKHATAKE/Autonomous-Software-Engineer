import base64
import io
import json
import subprocess
import sys
import tarfile
from contextlib import nullcontext
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import execution, github_service, llm_service


def test_download_repository_accepts_github_codeload_redirect(monkeypatch, tmp_path) -> None:
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
        content = b"repository source"
        member = tarfile.TarInfo("test-main/README.md")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))

    api_response = httpx.Response(
        302,
        headers={"location": "https://codeload.github.com/owner/test/legacy.tar.gz/refs/heads/main"},
        request=httpx.Request("GET", "https://api.github.com/repos/owner/test/tarball/main"),
    )
    archive_response = httpx.Response(
        200,
        content=archive_buffer.getvalue(),
        request=httpx.Request("GET", "https://codeload.github.com/owner/test/archive.tar.gz"),
    )
    requests: list[tuple[str, dict]] = []
    responses = [api_response, archive_response]

    def fake_stream(method, url, **kwargs):
        requests.append((url, kwargs))
        return nullcontext(responses.pop(0))

    monkeypatch.setattr(github_service.httpx, "stream", fake_stream)
    destination = tmp_path / "workspace"

    result = github_service.download_repository("owner/test", "main", "test-token", destination)

    assert result == destination
    assert (destination / "README.md").read_bytes() == b"repository source"
    assert len(requests) == 2
    assert requests[0][1]["follow_redirects"] is False
    assert requests[1][0].startswith("https://codeload.github.com/")


def test_check_patch_applies_reports_malformed_patch(monkeypatch, tmp_path) -> None:
    def fake_download(full_name, branch, token, destination):
        destination.mkdir(parents=True)
        (destination / "README.md").write_text("before\n", encoding="utf-8")
        return destination

    monkeypatch.setattr(github_service, "download_repository", fake_download)
    patch = "--- a/README.md\n+++ b/README.md\n@@ malformed @@\n-before\n+after\n"

    error = github_service.check_patch_applies(
        "owner/repository",
        "main",
        "github-token",
        patch,
    )

    assert error
    assert "patch" in error.lower()


def test_check_patch_applies_multifile_new_file_and_modification(monkeypatch, tmp_path) -> None:
    def fake_download(full_name, branch, token, destination):
        destination.mkdir(parents=True)
        (destination / "README.md").write_text("# test\n", encoding="utf-8")
        return destination

    monkeypatch.setattr(github_service, "download_repository", fake_download)
    patch = (
        "--- /dev/null\n"
        "+++ b/hello_world.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+print('hello world')\n"
        "+\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1,2 @@\n"
        " # test\n"
        "+\n"
    )

    error = github_service.check_patch_applies(
        "owner/repository",
        "main",
        "github-token",
        patch,
    )

    assert error is None


def test_build_patch_from_structured_edits_generates_applicable_multifile_diff(monkeypatch, tmp_path) -> None:
    def fake_download(full_name, branch, token, destination):
        destination.mkdir(parents=True)
        (destination / "README.md").write_text("# test\n", encoding="utf-8")
        return destination

    monkeypatch.setattr(github_service, "download_repository", fake_download)
    edits = {
        "files": [
            {
                "path": "hello_world.py",
                "action": "create",
                "content": 'def main():\n    print("hello world")\n',
            },
            {
                "path": "README.md",
                "action": "edit",
                "edits": [{"search": "# test\n", "replace": "# test\n\nRun `python hello_world.py`.\n"}],
            },
        ]
    }

    patch = github_service.build_patch_from_edits(
        "owner/repository",
        "main",
        "github-token",
        json.dumps(edits),
    )

    assert "diff --git a/hello_world.py b/hello_world.py" in patch
    assert "diff --git a/README.md b/README.md" in patch
    assert "def main():" in patch
    assert github_service.check_patch_applies(
        "owner/repository",
        "main",
        "github-token",
        patch,
    ) is None


def test_build_patch_from_structured_edits_requires_unique_match(monkeypatch, tmp_path) -> None:
    def fake_download(full_name, branch, token, destination):
        destination.mkdir(parents=True)
        (destination / "README.md").write_text("duplicate\ntext\nduplicate\n", encoding="utf-8")
        return destination

    monkeypatch.setattr(github_service, "download_repository", fake_download)
    edits = {
        "files": [
            {
                "path": "README.md",
                "action": "edit",
                "edits": [{"search": "duplicate", "replace": "unique"}],
            }
        ]
    }

    with pytest.raises(github_service.CoderEditError, match="matched 2 times"):
        github_service.build_patch_from_edits(
            "owner/repository",
            "main",
            "github-token",
            json.dumps(edits),
        )


def test_groq_model_defaults_to_active_model(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    assert llm_service.groq_model() == "qwen/qwen3.8-27b"


def test_groq_requires_api_key_before_generating_output(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(llm_service.LLMConfigurationError, match="Groq is not configured"):
        llm_service.generate_agent_output(
            "coder",
            {"title": "Add feature", "description": "Add a small utility."},
            "README content",
        )


def test_groq_completion_uses_configured_model_and_key(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    requests: list[dict] = []

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "analysis result"}}]}

    def fake_post(url, **kwargs):
        requests.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(llm_service.httpx, "post", fake_post)
    result = llm_service.generate_agent_output(
        "repository_analyzer",
        {"title": "Analyze code", "description": "Review the repository."},
        "README content",
    )
    assert result == "analysis result"
    assert requests[0]["json"]["model"] == "test-model"
    assert requests[0]["json"]["max_tokens"] == llm_service.MAX_OUTPUT_TOKENS["repository_analyzer"]
    assert requests[0]["headers"]["Authorization"] == "Bearer groq-test-key"


def test_groq_completion_retries_after_rate_limit_wait(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    responses = [
        httpx.Response(
            429,
            json={"error": {"message": "Please try again in 38.82s."}},
            request=httpx.Request("POST", llm_service.GROQ_API_URL),
        ),
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": "analysis result"}}]},
            request=httpx.Request("POST", llm_service.GROQ_API_URL),
        ),
    ]
    delays: list[float] = []
    calls: list[str] = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(llm_service.httpx, "post", fake_post)
    monkeypatch.setattr(llm_service.time, "sleep", delays.append)

    result = llm_service.generate_agent_output(
        "repository_analyzer",
        {"title": "Analyze code", "description": "Review the repository."},
        "README content",
    )

    assert result == "analysis result"
    assert len(calls) == 2
    assert delays == [pytest.approx(38.92)]


def test_groq_coder_retries_and_parses_structured_edits(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    outputs = [
        "I will update the file now.",
        '```json\n{"files":[{"path":"README.md","action":"edit","edits":[{"search":"Old","replace":"New"}]}]}\n```',
    ]
    requests: list[dict] = []

    class Response:
        status_code = 200

        def __init__(self, content: str) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": self.content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168},
            }

    def fake_post(url, **kwargs):
        requests.append(kwargs)
        return Response(outputs.pop(0))

    monkeypatch.setattr(llm_service.httpx, "post", fake_post)
    result = llm_service.generate_agent_output(
        "coder",
        {"title": "Update README", "description": "Change the old text."},
        "--- README.md ---\nOld",
    )

    assert json.loads(result) == {
        "files": [
            {
                "path": "README.md",
                "action": "edit",
                "edits": [{"search": "Old", "replace": "New"}],
            }
        ]
    }
    assert len(requests) == 2
    assert requests[0]["json"]["max_tokens"] == llm_service.MAX_OUTPUT_TOKENS["coder"]
    assert "Invalid structured coder response" in requests[1]["json"]["messages"][-1]["content"]
    assert result.completion_metadata[0]["usage"]["completion_tokens"] == 45


def test_groq_coder_retries_explicitly_when_response_was_truncated(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    outputs = [
        '{"files":[{"path":"main.cpp","action":"create","content":"int main() {"}',
        '{"files":[{"path":"main.cpp","action":"create","content":"int main() {\\n  return 0;\\n}\\n"}]}',
    ]
    requests: list[dict] = []

    class Response:
        status_code = 200

        def __init__(self, content: str) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "choices": [{
                    "message": {"content": self.content},
                    "finish_reason": "length" if len(requests) == 1 else "stop",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 100, "total_tokens": 110},
            }

    def fake_post(url, **kwargs):
        requests.append(kwargs)
        return Response(outputs.pop(0))

    monkeypatch.setattr(llm_service.httpx, "post", fake_post)
    edits_json = llm_service.generate_agent_output(
        "coder",
        {"title": "Create a C++ program", "description": "Add the requested program."},
        "No relevant files.",
    )

    assert json.loads(edits_json)["files"][0]["action"] == "create"
    assert len(requests) == 2
    assert "finish_reason=length" in requests[1]["json"]["messages"][-1]["content"]
    assert edits_json.completion_metadata[0]["finish_reason"] == "length"


def test_coder_edit_parser_rejects_missing_search_text() -> None:
    with pytest.raises(ValueError, match="non-empty search"):
        llm_service._parse_coder_edits(
            '{"files":[{"path":"main.cpp","action":"edit","edits":[{"search":"","replace":"new"}]}]}'
        )


def test_groq_completion_reports_missing_api_key(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(llm_service.LLMConfigurationError, match="GROQ_API_KEY"):
        llm_service.generate_agent_output(
            "planner",
            {"title": "Plan code", "description": "Create a plan."},
            "Repository context",
        )


def test_validation_command_runs_with_docker_constraints(monkeypatch, tmp_path) -> None:
    observed: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        observed.append((command, kwargs))
        if command[1] == "create":
            return subprocess.CompletedProcess(command, 0, stdout="container-id\n", stderr="")
        if command[1] == "exec":
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(execution.subprocess, "run", fake_run)
    monkeypatch.setattr(execution, "EXECUTION_IMAGE", "test-runner:latest")
    monkeypatch.setattr(execution, "EXECUTION_NETWORK", "none")
    result = execution.run_local_command("task-id", "python --version", cwd=tmp_path)
    command = observed[0][0]
    assert command[0:2] == ["docker", "create"]
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--memory=1g" in command
    assert "--cap-drop=ALL" in command
    assert observed[1][0][0:2] == ["docker", "start"]
    assert observed[2][0][0:3] == ["docker", "exec", "--interactive"]
    assert observed[3][0][0:3] == ["docker", "exec", "--workdir"]
    assert observed[4][0][0:3] == ["docker", "rm", "--force"]
    assert result["success"] is True
    assert result["stdout"] == "ok"


@pytest.mark.parametrize("command", ["powershell -Command whoami", "python --version && echo unsafe"])
def test_validation_rejects_unapproved_commands(command: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        execution.run_local_command("task-id", command, cwd=tmp_path)


def test_patch_publish_creates_branch_with_changed_file(monkeypatch, tmp_path) -> None:
    requests: list[tuple[str, str, dict]] = []
    responses = [
        {"object": {"sha": "base-sha"}},
        {"tree": {"sha": "base-tree"}},
        {"sha": "new-blob"},
        {"sha": "new-tree"},
        {"sha": "new-commit"},
        {},
    ]

    class Response:
        def __init__(self, value: dict) -> None:
            self.value = value

        def json(self) -> dict:
            return self.value

    def fake_download(full_name, branch, token, destination):
        destination.mkdir(parents=True)
        (destination / "README.md").write_text("before\n", encoding="utf-8")
        return destination

    def fake_request(method, path, token, **kwargs):
        requests.append((method, path, kwargs.get("json", {})))
        return Response(responses.pop(0))

    monkeypatch.setattr(github_service, "download_repository", fake_download)
    monkeypatch.setattr(github_service, "_request", fake_request)
    result = github_service.publish_patch_as_branch(
        "owner/repository",
        "main",
        "ase/task-test",
        "github-token",
        "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-before\n+after\n",
    )
    assert result == "new-commit"
    assert [request[0] for request in requests] == ["GET", "GET", "POST", "POST", "POST", "POST"]
    assert requests[-1][2]["ref"] == "refs/heads/ase/task-test"


def test_patch_publish_includes_new_files_in_generated_tree(monkeypatch, tmp_path) -> None:
    requests: list[tuple[str, str, dict]] = []
    responses = [
        {"object": {"sha": "base-sha"}},
        {"tree": {"sha": "base-tree"}},
        {"sha": "new-blob"},
        {"sha": "new-tree"},
        {"sha": "new-commit"},
        {},
    ]

    class Response:
        def __init__(self, value: dict) -> None:
            self.value = value

        def json(self) -> dict:
            return self.value

    def fake_download(full_name, branch, token, destination):
        destination.mkdir(parents=True)
        (destination / "README.md").write_text("base\n", encoding="utf-8")
        return destination

    def fake_request(method, path, token, **kwargs):
        requests.append((method, path, kwargs.get("json", {})))
        return Response(responses.pop(0))

    monkeypatch.setattr(github_service, "download_repository", fake_download)
    monkeypatch.setattr(github_service, "_request", fake_request)
    static_patch = (
        "--- /dev/null\n"
        "+++ b/add_numbers.py\n"
        "@@ -0,0 +1,8 @@\n"
        "+def add_numbers(a: float, b: float) -> float:\n"
        '+    """Return the sum of two numbers."""\n'
        "+    return a + b\n"
        "+\n"
        "+\n"
        '+if __name__ == "__main__":\n'
        '+    first = float(input("Enter first number: "))\n'
        '+    second = float(input("Enter second number: "))\n'
        '+    print(f"Sum: {add_numbers(first, second)}")\n'
    )

    github_service.publish_patch_as_branch(
        "owner/repository",
        "main",
        "ase/task-addition",
        "github-token",
        static_patch,
    )

    blob = next(payload for method, path, payload in requests if path.endswith("/git/blobs"))
    assert blob["encoding"] == "base64"
    assert b"def add_numbers" in base64.b64decode(blob["content"])
