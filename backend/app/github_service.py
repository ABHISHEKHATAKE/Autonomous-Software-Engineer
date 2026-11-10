from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import GITHUB_API_URL, GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_REDIRECT_URI, SECRET_KEY
from app.models import UserCredential

_REPOSITORY_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".lock")


class GitHubServiceError(RuntimeError):
    pass


class CoderEditError(ValueError):
    pass


def _cipher() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_token(token: str) -> str:
    return _cipher().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_token(encrypted_token: str) -> str:
    try:
        return _cipher().decrypt(encrypted_token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise GitHubServiceError("Stored GitHub credential cannot be decrypted; configure it again.") from exc


def get_user_github_token(db: Session, user_id: str) -> str | None:
    credential = (
        db.query(UserCredential)
        .filter(UserCredential.user_id == user_id, UserCredential.provider == "github")
        .first()
    )
    if credential:
        return decrypt_token(credential.encrypted_token)
    return None


def save_user_github_token(db: Session, user_id: str, token: str) -> None:
    cleaned = token.strip()
    if not cleaned:
        raise GitHubServiceError("GitHub token is required.")
    credential = (
        db.query(UserCredential)
        .filter(UserCredential.user_id == user_id, UserCredential.provider == "github")
        .first()
    )
    if credential is None:
        credential = UserCredential(user_id=user_id, provider="github", encrypted_token=encrypt_token(cleaned))
        db.add(credential)
    else:
        credential.encrypted_token = encrypt_token(cleaned)
    db.commit()


def _headers(token: str | None) -> dict[str, str]:
    if not token:
        raise GitHubServiceError("Connect a GitHub token before using this feature.")
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _request(method: str, path: str, token: str, **kwargs: Any) -> httpx.Response:
    try:
        response = httpx.request(
            method,
            f"{GITHUB_API_URL}{path}",
            headers={**_headers(token), **kwargs.pop("headers", {})},
            timeout=30,
            follow_redirects=True,
            **kwargs,
        )
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as exc:
        detail = "GitHub rejected the request. Check token permissions, repository access, and branch names."
        try:
            message = exc.response.json().get("message")
            if message:
                detail = f"GitHub request failed: {message}"
        except (ValueError, AttributeError):
            pass
        raise GitHubServiceError(detail) from exc
    except httpx.HTTPError as exc:
        raise GitHubServiceError(f"Unable to reach GitHub: {exc}") from exc


def validate_github_token(token: str) -> dict[str, str]:
    response = _request("GET", "/user", token)
    payload = response.json()
    return {"login": str(payload.get("login", ""))}


def create_oauth_authorization_url(state: str) -> str:
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise GitHubServiceError("Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET to enable GitHub OAuth.")
    query = urlencode(
        {
            "client_id": GITHUB_CLIENT_ID,
            "redirect_uri": GITHUB_REDIRECT_URI,
            "scope": "repo read:org user:email",
            "state": state,
        }
    )
    return f"https://github.com/login/oauth/authorize?{query}"


def exchange_oauth_code(code: str, state: str) -> str:
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise GitHubServiceError("Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET to enable GitHub OAuth.")
    try:
        response = httpx.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/vnd.github+json"},
            json={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": GITHUB_REDIRECT_URI,
                "state": state,
            },
            timeout=30,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise GitHubServiceError("GitHub OAuth did not return an access token.")
        return token
    except httpx.HTTPError as exc:
        raise GitHubServiceError(f"GitHub OAuth exchange failed: {exc}") from exc


def get_github_repositories(token: str | None = None) -> list[dict[str, Any]]:
    response = _request("GET", "/user/repos?per_page=100&sort=updated", token or "")
    payload = response.json()
    return [
        {
            "full_name": item["full_name"],
            "name": item["name"],
            "default_branch": item.get("default_branch") or "main",
            "primary_language": item.get("language") or "Unknown",
            "description": item.get("description") or "",
        }
        for item in payload
        if isinstance(item, dict) and item.get("full_name") and item.get("name")
    ]


def _repository_path(full_name: str) -> str:
    if not _REPOSITORY_NAME.fullmatch(full_name):
        raise GitHubServiceError("Repository name must be in owner/repository format.")
    owner, repository = full_name.split("/", 1)
    return f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}"


def _repository_tree(full_name: str, branch: str, token: str) -> list[dict[str, Any]]:
    path = _repository_path(full_name)
    response = _request("GET", f"{path}/git/trees/{quote(branch, safe='')}?recursive=1", token)
    tree = response.json().get("tree", [])
    return [
        item
        for item in tree
        if isinstance(item, dict)
        and item.get("type") == "blob"
        and isinstance(item.get("path"), str)
        and not item["path"].lower().endswith(_SKIP_SUFFIXES)
    ]


def repo_structure_for(full_name: str, explicit_token: str | None = None, branch: str | None = None) -> list[str]:
    if not explicit_token:
        raise GitHubServiceError("Connect a GitHub token before indexing repositories.")
    tree = _repository_tree(full_name, branch or "main", explicit_token)
    return [item["path"] for item in tree[:100]]


def get_repository_context(
    full_name: str,
    branch: str,
    token: str,
    *,
    max_files: int = 18,
    max_file_chars: int = 5000,
) -> str:
    path = _repository_path(full_name)
    tree = _repository_tree(full_name, branch, token)
    candidates = sorted(
        tree,
        key=lambda item: (
            0 if item["path"].lower().endswith(("readme.md", "pyproject.toml", "package.json")) else 1,
            item["path"],
        ),
    )[:max_files]
    excerpts: list[str] = []
    for item in candidates:
        file_response = _request(
            "GET",
            f"{path}/contents/{quote(item['path'], safe='/')}?ref={quote(branch, safe='')}",
            token,
        )
        content = file_response.json()
        if content.get("encoding") != "base64" or not isinstance(content.get("content"), str):
            continue
        try:
            decoded = base64.b64decode(content["content"], validate=False).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        excerpts.append(f"--- {item['path']} ---\n{decoded[:max_file_chars]}")
    if not excerpts:
        raise GitHubServiceError("The selected repository branch contains no readable source files.")
    return "\n\n".join(excerpts)


def download_repository(full_name: str, branch: str, token: str, destination: Path) -> Path:
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{destination.name}-", dir=destination.parent) as temporary_directory:
        temporary_root = Path(temporary_directory)
        archive_path = temporary_root / "repository.tar.gz"
        api_url = f"{GITHUB_API_URL}{_repository_path(full_name)}/tarball/{quote(branch, safe='')}"
        try:
            with httpx.stream(
                "GET",
                api_url,
                headers=_headers(token),
                timeout=60,
                follow_redirects=False,
            ) as response:
                download_url = None
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise GitHubServiceError("GitHub redirected the archive request without a destination.")
                    download_url = urljoin(api_url, location)
                    parsed_url = urlparse(download_url)
                    api_host = urlparse(GITHUB_API_URL).hostname
                    if parsed_url.scheme != "https" or parsed_url.hostname not in {"codeload.github.com", api_host}:
                        raise GitHubServiceError("GitHub returned an unexpected repository archive URL.")
                else:
                    response.raise_for_status()
                    _write_archive(response, archive_path)

            if download_url:
                with httpx.stream("GET", download_url, timeout=60, follow_redirects=False) as response:
                    response.raise_for_status()
                    _write_archive(response, archive_path)

            staging = temporary_root / "repository"
            staging.mkdir()
            root = staging.resolve()
            total_size = 0
            with tarfile.open(archive_path, mode="r:gz") as archive:
                for member in archive:
                    path = PurePosixPath(member.name)
                    relative_parts = path.parts[1:]
                    if not relative_parts or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                        continue
                    if any(part in {"", ".", ".."} or "\\" in part or ":" in part for part in relative_parts):
                        raise GitHubServiceError("GitHub archive contains an unsafe path.")
                    target = root.joinpath(*relative_parts).resolve()
                    if not target.is_relative_to(root):
                        raise GitHubServiceError("GitHub archive contains a path outside the repository.")
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    total_size += member.size
                    if total_size > 100 * 1024 * 1024:
                        raise GitHubServiceError("Repository archive exceeds the 100 MB extraction limit.")
                    source = archive.extractfile(member)
                    if source is None:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source, target.open("wb") as output:
                        output.write(source.read())
            if not any(root.iterdir()):
                raise GitHubServiceError("GitHub returned an empty repository archive.")
            root.replace(destination)
        except GitHubServiceError:
            raise
        except (httpx.HTTPError, OSError, tarfile.TarError) as exc:
            raise GitHubServiceError(f"Unable to download or extract repository archive: {exc}") from exc
    return destination


def build_patch_from_edits(full_name: str, branch: str, token: str, edits_json: str) -> str:
    try:
        response = json.loads(edits_json)
    except json.JSONDecodeError as exc:
        raise CoderEditError(f"Coder response is not valid JSON: {exc}") from exc
    if not isinstance(response, dict) or set(response) != {"files"} or not isinstance(response["files"], list):
        raise CoderEditError('Coder response must contain a "files" array.')
    operations = response["files"]
    if not operations:
        raise CoderEditError("Coder returned no file operations.")

    with tempfile.TemporaryDirectory(prefix="ase-edit-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        workspace = temporary_root / "repository"
        download_repository(full_name, branch, token, workspace)
        root = workspace.resolve()
        git_support = temporary_root / "git-support"
        git_support.mkdir()
        empty_git_config = git_support / "config"
        empty_git_config.write_text("", encoding="utf-8")
        hooks_directory = git_support / "hooks"
        hooks_directory.mkdir()
        git_environment = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("GIT_")
        }
        git_environment.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(empty_git_config),
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": str(git_support),
        })

        def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
            try:
                result = subprocess.run(
                    ["git", "-c", f"core.hooksPath={hooks_directory}", "-c", "core.autocrlf=false", *args],
                    cwd=str(workspace),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                    env=git_environment,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise GitHubServiceError(f"Unable to generate a patch from coder edits: {exc}") from exc
            if check and result.returncode:
                raise GitHubServiceError(
                    f"Unable to generate a patch from coder edits: {result.stderr.strip() or result.stdout.strip()}"
                )
            return result

        if (workspace / ".git").exists():
            raise GitHubServiceError("Repository archive unexpectedly contains Git metadata.")
        run_git("init", "--quiet")
        run_git("config", "user.name", "Autonomous Software Engineer")
        run_git("config", "user.email", "ase-bot@users.noreply.github.com")
        run_git("add", "--all", "--force")
        run_git("commit", "--quiet", "--allow-empty", "-m", "Repository base snapshot")

        seen_paths: set[str] = set()
        for operation in operations:
            if not isinstance(operation, dict):
                raise CoderEditError("Each coder file operation must be an object.")
            path = operation.get("path")
            action = operation.get("action")
            if not isinstance(path, str) or not path or "\0" in path or "\\" in path or ":" in path:
                raise CoderEditError(f"Unsafe or missing file path: {path!r}.")
            pure_path = PurePosixPath(path)
            if pure_path.is_absolute() or any(
                part in {"", ".", ".."} or part.lower() == ".git"
                for part in pure_path.parts
            ):
                raise CoderEditError(f"Unsafe repository path: {path!r}.")
            normalized_path = pure_path.as_posix()
            if normalized_path in seen_paths:
                raise CoderEditError(f"File {normalized_path!r} has more than one operation.")
            seen_paths.add(normalized_path)
            target = workspace.joinpath(*pure_path.parts)
            if not target.resolve().is_relative_to(root):
                raise CoderEditError(f"File path escapes the repository: {normalized_path!r}.")
            if any(parent.is_symlink() for parent in target.parents if parent != workspace.parent):
                raise CoderEditError(f"File path traverses a symbolic link: {normalized_path!r}.")
            if target.is_symlink():
                raise CoderEditError(f"Cannot edit symbolic links: {normalized_path!r}.")

            if action == "create":
                content = operation.get("content")
                if set(operation) != {"path", "action", "content"} or not isinstance(content, str):
                    raise CoderEditError(f"Create operation for {normalized_path!r} requires string content.")
                if target.exists():
                    raise CoderEditError(f"Cannot create {normalized_path!r}: the file already exists.")
                if "\0" in content:
                    raise CoderEditError(f"Created file contains a NUL byte: {normalized_path!r}.")
                if len(content.encode("utf-8")) > 5 * 1024 * 1024:
                    raise CoderEditError(f"Created file exceeds the 5 MB limit: {normalized_path!r}.")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content.replace("\r\n", "\n").encode("utf-8"))
            elif action == "edit":
                edits = operation.get("edits")
                if (
                    set(operation) != {"path", "action", "edits"}
                    or not isinstance(edits, list)
                    or not edits
                ):
                    raise CoderEditError(f"Edit operation for {normalized_path!r} requires edits.")
                if not target.is_file():
                    raise CoderEditError(f"Cannot edit {normalized_path!r}: it is not an existing file.")
                if target.stat().st_size > 5 * 1024 * 1024:
                    raise CoderEditError(f"Edited file exceeds the 5 MB limit: {normalized_path!r}.")
                try:
                    source = target.read_bytes().decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise CoderEditError(f"Cannot edit non-UTF-8 file {normalized_path!r}.") from exc
                newline = "\r\n" if "\r\n" in source else "\n"
                source = source.replace("\r\n", "\n")
                for edit in edits:
                    if (
                        not isinstance(edit, dict)
                        or set(edit) != {"search", "replace"}
                        or not isinstance(edit.get("search"), str)
                        or not edit["search"]
                        or not isinstance(edit.get("replace"), str)
                    ):
                        raise CoderEditError(f"Invalid search/replace edit for {normalized_path!r}.")
                    if "\0" in edit["search"] or "\0" in edit["replace"]:
                        raise CoderEditError(f"Search/replace edit contains a NUL byte for {normalized_path!r}.")
                    search = edit["search"].replace("\r\n", "\n")
                    replacement = edit["replace"].replace("\r\n", "\n")
                    occurrences = source.count(search)
                    if occurrences != 1:
                        raise CoderEditError(
                            f"Search text for {normalized_path!r} matched {occurrences} times; expected exactly once."
                        )
                    source = source.replace(search, replacement, 1)
                target.write_bytes(source.replace("\n", newline).encode("utf-8"))
            elif action == "delete":
                if set(operation) != {"path", "action"} or not target.is_file():
                    raise CoderEditError(f"Cannot delete {normalized_path!r}: it is not an existing regular file.")
                target.unlink()
            else:
                raise CoderEditError(f"Unsupported action for {normalized_path!r}: {action!r}.")

        run_git("add", "--all", "--force")
        generated = run_git("diff", "--cached", "--binary", "--full-index", "--no-ext-diff", "HEAD", "--")
        if not generated.stdout:
            raise CoderEditError("Coder edits did not change any repository files.")
        if len(generated.stdout) > 100_000:
            raise CoderEditError("Generated patch exceeds the 100 KB limit.")
        return generated.stdout


def check_patch_applies(full_name: str, branch: str, token: str, patch: str) -> str | None:
    with tempfile.TemporaryDirectory(prefix="ase-patch-check-") as temporary_directory:
        workspace = Path(temporary_directory) / "repository"
        download_repository(full_name, branch, token, workspace)
        try:
            result = subprocess.run(
                ["git", "apply", "--check", "--whitespace=fix", "-"],
                cwd=str(workspace),
                input=patch,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubServiceError(f"Unable to validate generated patch: {exc}") from exc
        if result.returncode:
            return result.stderr.strip() or "Git rejected the patch."
        return None


def _write_archive(response: httpx.Response, destination: Path) -> None:
    total_size = 0
    with destination.open("wb") as archive_file:
        for chunk in response.iter_bytes():
            total_size += len(chunk)
            if total_size > 100 * 1024 * 1024:
                raise GitHubServiceError("Repository archive exceeds the 100 MB download limit.")
            archive_file.write(chunk)


def publish_patch_as_branch(
    full_name: str,
    base_branch: str,
    head_branch: str,
    token: str,
    patch: str,
) -> str:
    with tempfile.TemporaryDirectory(prefix="ase-publish-") as temporary_directory:
        workspace = Path(temporary_directory) / "repository"
        return _publish_patch_as_branch(full_name, base_branch, head_branch, token, patch, workspace)


def _publish_patch_as_branch(
    full_name: str,
    base_branch: str,
    head_branch: str,
    token: str,
    patch: str,
    workspace: Path,
) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,120}", head_branch) or head_branch.startswith("/") or ".." in head_branch.split("/"):
        raise GitHubServiceError("Feature branch name is invalid.")
    if head_branch == base_branch:
        raise GitHubServiceError("Feature branch must differ from the base branch.")

    download_repository(full_name, base_branch, token, workspace)
    git_support = workspace.parent / "git-support"
    git_support.mkdir()
    empty_git_config = git_support / "config"
    empty_git_config.write_text("", encoding="utf-8")
    hooks_directory = git_support / "hooks"
    hooks_directory.mkdir()
    git_environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    git_environment.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(empty_git_config),
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(git_support),
    })

    def run_git(*args: str, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", "-c", f"core.hooksPath={hooks_directory}", *args],
                cwd=str(workspace),
                input=input_text,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env=git_environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubServiceError(f"Unable to prepare GitHub branch: {exc}") from exc
        if check and result.returncode:
            raise GitHubServiceError(f"Unable to prepare GitHub branch: {result.stderr.strip()}")
        return result

    if (workspace / ".git").exists():
        raise GitHubServiceError("A publish workspace already exists; use a new task branch.")
    run_git("init", "--quiet")
    run_git("config", "user.name", "Autonomous Software Engineer")
    run_git("config", "user.email", "ase-bot@users.noreply.github.com")
    run_git("add", "--all")
    run_git("commit", "--quiet", "--allow-empty", "-m", "Repository base snapshot")
    check = run_git("apply", "--check", "-", check=False, input_text=patch)
    if check.returncode:
        raise GitHubServiceError(f"Generated patch no longer applies: {check.stderr.strip()}")
    run_git("apply", "-", input_text=patch)
    run_git("add", "--all")
    changed = run_git("diff", "--cached", "--name-status", "-z", "HEAD").stdout.split("\0")
    changes: list[tuple[str, str]] = []
    index = 0
    while index < len(changed) and changed[index]:
        status_code = changed[index]
        index += 1
        old_path = None
        if status_code.startswith(("R", "C")):
            if index >= len(changed):
                raise GitHubServiceError("Unable to read renamed paths from the generated patch.")
            old_path = changed[index]
            index += 1
        if index >= len(changed):
            raise GitHubServiceError("Unable to read changed paths from the generated patch.")
        changed_path = changed[index]
        index += 1
        if "\\" in changed_path or ":" in changed_path:
            raise GitHubServiceError("Generated patch contains an unsafe file path.")
        if old_path and status_code.startswith("R"):
            if "\\" in old_path or ":" in old_path:
                raise GitHubServiceError("Generated patch contains an unsafe file path.")
            changes.append(("D", old_path))
        if status_code.startswith("D"):
            changes.append(("D", changed_path))
        else:
            changes.append(("M", changed_path))
    if not changes:
        raise GitHubServiceError("Generated patch contains no changes.")

    repository_path = _repository_path(full_name)
    reference = _request(
        "GET",
        f"{repository_path}/git/ref/heads/{quote(base_branch, safe='/')}",
        token,
    ).json()
    base_commit = reference["object"]["sha"]
    commit = _request("GET", f"{repository_path}/git/commits/{base_commit}", token).json()
    tree_entries: list[dict[str, Any]] = []
    for action, changed_path in changes:
        pure_path = PurePosixPath(changed_path)
        if pure_path.is_absolute() or any(part in {"", ".", ".."} for part in pure_path.parts):
            raise GitHubServiceError("Generated patch contains an unsafe file path.")
        file_path = workspace.joinpath(*pure_path.parts)
        if action == "D":
            tree_entries.append({"path": changed_path, "mode": "100644", "type": "blob", "sha": None})
            continue
        if not file_path.is_file() or file_path.is_symlink():
            raise GitHubServiceError("Generated patch may only add or modify regular files.")
        contents = file_path.read_bytes()
        if len(contents) > 5 * 1024 * 1024:
            raise GitHubServiceError(f"Changed file exceeds the 5 MB publishing limit: {changed_path}")
        blob = _request(
            "POST",
            f"{repository_path}/git/blobs",
            token,
            json={"content": base64.b64encode(contents).decode("ascii"), "encoding": "base64"},
        ).json()
        tree_entries.append({"path": changed_path, "mode": "100644", "type": "blob", "sha": blob["sha"]})

    new_tree = _request(
        "POST",
        f"{repository_path}/git/trees",
        token,
        json={"base_tree": commit["tree"]["sha"], "tree": tree_entries},
    ).json()
    new_commit = _request(
        "POST",
        f"{repository_path}/git/commits",
        token,
        json={
            "message": "Apply autonomous task patch",
            "tree": new_tree["sha"],
            "parents": [base_commit],
        },
    ).json()
    try:
        _request(
            "POST",
            f"{repository_path}/git/refs",
            token,
            json={"ref": f"refs/heads/{head_branch}", "sha": new_commit["sha"]},
        )
    except GitHubServiceError as create_error:
        try:
            existing_ref = _request(
                "GET",
                f"{repository_path}/git/ref/heads/{quote(head_branch, safe='/')}",
                token,
            ).json()
            existing_commit = _request(
                "GET",
                f"{repository_path}/git/commits/{existing_ref['object']['sha']}",
                token,
            ).json()
        except GitHubServiceError:
            raise create_error
        if existing_commit.get("tree", {}).get("sha") == new_tree["sha"]:
            return existing_ref["object"]["sha"]
        raise GitHubServiceError("Feature branch already exists with different content; choose a fresh branch.") from create_error
    return new_commit["sha"]


def create_github_pull_request(
    full_name: str,
    token: str,
    *,
    title: str,
    head: str,
    base: str,
    body: str,
) -> dict[str, Any]:
    response = _request(
        "POST",
        f"{_repository_path(full_name)}/pulls",
        token,
        json={"title": title, "head": head, "base": base, "body": body, "draft": True},
    )
    result = response.json()
    return {"number": result["number"], "html_url": result["html_url"], "state": result["state"]}
