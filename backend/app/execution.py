from __future__ import annotations

import io
import shlex
import subprocess
import tarfile
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.config import EXECUTION_IMAGE, EXECUTION_NETWORK

SAFE_BINARIES = {
    "python",
    "python3",
    "pytest",
    "npm",
    "node",
    "npx",
    "uvicorn",
    "git",
    "echo",
}


class ExecutionError(RuntimeError):
    pass


def _pack_workspace(working_directory: Path) -> bytes:
    archive_buffer = io.BytesIO()
    total_size = 0
    with tarfile.open(fileobj=archive_buffer, mode="w") as archive:
        for path in working_directory.rglob("*"):
            relative_path = path.relative_to(working_directory)
            if path.is_symlink() or any(part in {"", ".", ".."} for part in relative_path.parts):
                raise ExecutionError("Execution workspace contains an unsafe path or symbolic link.")
            if path.is_file():
                total_size += path.stat().st_size
                if total_size > 100 * 1024 * 1024:
                    raise ExecutionError("Execution workspace exceeds the 100 MB container staging limit.")
            archive.add(path, arcname=relative_path.as_posix(), recursive=False)
    return archive_buffer.getvalue()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_command_for_repo(repo_name: str, primary_language: str | None = None) -> str:
    lang = (primary_language or "").lower()
    if "python" in lang:
        return "python -m pytest -q -p no:cacheprovider"
    if "typescript" in lang or "javascript" in lang:
        return "npm run build"
    if repo_name.endswith("ase") or "ase" in repo_name.lower():
        return "python -m pytest -q -p no:cacheprovider"
    return "python --version"


def run_local_command(task_id: str, command: str, *, cwd: str | Path, timeout_seconds: int = 120) -> dict[str, object]:
    if not command or not command.strip():
        raise ValueError("A command is required for execution.")
    if EXECUTION_NETWORK not in {"none", "bridge"}:
        raise ValueError("EXECUTION_NETWORK must be either 'none' or 'bridge'.")

    try:
        tokens = shlex.split(command.strip())
    except ValueError as exc:
        raise ValueError("Command could not be parsed.") from exc
    if not tokens:
        raise ValueError("Command could not be parsed.")

    executable = tokens[0].lower()
    if executable not in SAFE_BINARIES and not executable.endswith(("python.exe", "npm.cmd")):
        raise ValueError(f"Command '{command}' is not allowed in the execution container.")
    if any(token in {";", "&&", "||", "|", ">", "<", "`"} for token in tokens):
        raise ValueError("Shell operators are disabled inside the execution container.")

    working_directory = Path(cwd).resolve()
    if not working_directory.is_dir():
        raise ValueError("Execution working directory does not exist.")

    container_name = f"ase-task-{uuid4().hex}"
    docker_command = [
        "docker",
        "create",
        "--name",
        container_name,
        "--network",
        EXECUTION_NETWORK,
        "--cpus=1",
        "--memory=1g",
        "--pids-limit=128",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m",
        "--tmpfs",
        "/workspace:rw,nosuid,size=1g",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user=0:0",
        "--env",
        "HOME=/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "npm_config_cache=/tmp/npm-cache",
        "--workdir",
        "/tmp",
        EXECUTION_IMAGE,
        "sleep",
        "infinity",
    ]
    started_at = time.monotonic()
    container_id: str | None = None
    try:
        created = subprocess.run(
            docker_command,
            cwd=str(working_directory),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if created.returncode:
            raise ExecutionError(created.stderr.strip() or created.stdout.strip() or "Docker could not create the execution container.")
        container_id = created.stdout.strip()
        if not container_id:
            raise ExecutionError("Docker created an execution container without returning its identifier.")

        started = subprocess.run(
            ["docker", "start", container_id],
            cwd=str(working_directory),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if started.returncode:
            raise ExecutionError(started.stderr.strip() or "Docker could not start the execution container.")

        workspace_archive = _pack_workspace(working_directory)
        staged = subprocess.run(
            ["docker", "exec", "--interactive", container_id, "tar", "-xf", "-", "-C", "/workspace"],
            cwd=str(working_directory),
            input=workspace_archive,
            capture_output=True,
            text=False,
            timeout=120,
            check=False,
        )
        if staged.returncode:
            error = staged.stderr.decode(errors="replace").strip()
            raise ExecutionError(error or "Docker could not stage the repository snapshot.")

        completed = subprocess.run(
            ["docker", "exec", "--workdir", "/workspace", container_id, *tokens],
            cwd=str(working_directory),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode == 125:
            raise ExecutionError(completed.stderr.strip() or "Docker could not execute the validation command.")
    except FileNotFoundError:
        raise
    except subprocess.TimeoutExpired:
        raise
    finally:
        if container_id:
            removed = subprocess.run(
                ["docker", "rm", "--force", container_id],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if removed.returncode:
                raise ExecutionError(removed.stderr.strip() or "Docker could not remove the execution container.")

    return {
        "task_id": task_id,
        "command": command.strip(),
        "exit_code": completed.returncode,
        "success": completed.returncode == 0,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "duration_ms": int((time.monotonic() - started_at) * 1000),
        "working_directory": str(working_directory),
        "created_at": datetime.utcnow().isoformat(),
    }
