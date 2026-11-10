import asyncio
import hashlib
import json
import secrets
import subprocess
from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.config import CORS_ORIGINS, ENVIRONMENT, FRONTEND_URL, PROJECT_NAME, SECRET_KEY
from app.database import SessionLocal, get_db, init_db

init_db()
from app.execution import ExecutionError, _project_root, default_command_for_repo, run_local_command
from app.github_service import (
    CoderEditError,
    GitHubServiceError,
    build_patch_from_edits,
    check_patch_applies,
    create_github_pull_request,
    create_oauth_authorization_url,
    download_repository,
    exchange_oauth_code,
    get_github_repositories,
    get_repository_context,
    get_user_github_token,
    publish_patch_as_branch,
    repo_structure_for,
    save_user_github_token,
    validate_github_token,
)
from app.llm_service import LLMConfigurationError, LLMProviderError, generate_agent_output, groq_configured, groq_model
from app.models import EventLog, GitHubOAuthState, PullRequest, Repository, Task, User
from app.orchestrator import next_workflow_step, workflow_steps_for_task
from app.schemas import DashboardResponse, ExecutionRequest, ExecutionResult, GitHubOAuthCallback, GitHubTokenRequest, LoginRequest, PhaseReport, PhaseStatus, PullRequestCreate, PullRequestResponse, RepositoryCreate, RepositoryIndexResponse, RepositoryResponse, RepositoryStructureResponse, TaskCreate, TaskLogResponse, TaskResponse, TokenResponse, UserCreate, UserResponse, WorkflowStatusResponse
from app.security import create_access_token, get_current_user, hash_password, verify_password

app = FastAPI(title=PROJECT_NAME, version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PHASES = [
    {"phase": 1, "name": "Foundation", "description": "Monorepo, backend, frontend, database, and auth foundation", "status": "completed"},
    {"phase": 2, "name": "GitHub integration", "description": "Repository discovery, metadata, and GitHub connectivity", "status": "completed"},
    {"phase": 3, "name": "Repository analyzer", "description": "Repository scanning, language detection, and structure summaries", "status": "completed"},
    {"phase": 4, "name": "Agent orchestration", "description": "Workflow orchestration and sequential task processing", "status": "completed"},
    {"phase": 5, "name": "Execution engine", "description": "Sandboxed execution, commands, logs, and cleanup", "status": "completed"},
    {"phase": 6, "name": "Debugging and review", "description": "Test execution, failure classification, and review", "status": "completed"},
    {"phase": 7, "name": "GitHub PR", "description": "Approval-gated branch publishing and draft pull requests", "status": "completed"},
    {"phase": 8, "name": "Dashboard", "description": "Operational UI, workflow state, diff viewer, and PR status", "status": "completed"},
    {"phase": 9, "name": "Hardening", "description": "Operational hardening and production deployment configuration", "status": "in_progress"},
]


def ensure_demo_data(db: Session) -> None:
    if ENVIRONMENT != "development":
        return
    user = db.query(User).filter(User.email == "demo@ase.dev").first()
    if user is None:
        user = User(name="Demo Engineer", email="demo@ase.dev", password_hash=hash_password("password123"))
        db.add(user)
        db.commit()
        db.refresh(user)

def emit_task_event(task_id: str, event_type: str, message: str, **payload: Any) -> None:
    event = {
        "event": event_type,
        "task_id": task_id,
        "message": message,
        "timestamp": datetime.utcnow().isoformat(),
    }
    event.update(payload)
    db = SessionLocal()
    try:
        log = EventLog(task_id=task_id, event_type=event_type, message=message, payload=json.dumps(payload, default=str))
        db.add(log)
        db.commit()
    finally:
        db.close()


@app.on_event("startup")
def startup_event() -> None:
    if ENVIRONMENT != "development" and (SECRET_KEY == "dev-secret-key-change-me" or len(SECRET_KEY) < 32):
        raise RuntimeError("Set a unique SECRET_KEY of at least 32 characters outside development.")
    init_db()
    db = SessionLocal()
    try:
        ensure_demo_data(db)
    finally:
        db.close()


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": PROJECT_NAME}


@app.post("/api/v1/auth/register", response_model=TokenResponse)
def register_user(payload: UserCreate, db: Session = Depends(get_db)) -> TokenResponse:
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(name=payload.name, email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.email)
    return TokenResponse(
        access_token=token,
        user={"name": user.name, "email": user.email},
    )


@app.post("/api/v1/auth/login", response_model=TokenResponse)
def login_user(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    ensure_demo_data(db)
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(user.email)
    return TokenResponse(
        access_token=token,
        user={"name": user.name, "email": user.email},
    )


@app.get("/api/v1/users/me", response_model=UserResponse)
def get_my_profile(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        created_at=current_user.created_at,
    )


@app.get("/api/v1/repositories", response_model=list[RepositoryResponse])
def list_repositories(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[RepositoryResponse]:
    ensure_demo_data(db)
    repos = db.query(Repository).filter(Repository.user_id == current_user.id).all()

    return [
        RepositoryResponse(
            id=repo.id,
            user_id=repo.user_id,
            github_repo_id=repo.github_repo_id,
            full_name=repo.full_name,
            name=repo.name,
            default_branch=repo.default_branch,
            primary_language=repo.primary_language,
            indexing_status=repo.indexing_status,
            created_at=repo.created_at,
        )
        for repo in repos
    ]


@app.post("/api/v1/github/token")
def save_github_token(
    payload: GitHubTokenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        identity = validate_github_token(payload.token)
        save_user_github_token(db, current_user.id, payload.token)
    except GitHubServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"status": "configured", "provider": "github", "account": identity["login"]}


@app.get("/api/v1/github/config")
def github_config(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, bool]:
    return {"configured": bool(get_user_github_token(db, current_user.id))}


@app.get("/api/v1/github/oauth/url")
def github_oauth_url(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    state = secrets.token_urlsafe(32)
    try:
        url = create_oauth_authorization_url(state)
    except GitHubServiceError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    db.query(GitHubOAuthState).filter(
        GitHubOAuthState.user_id == current_user.id,
        GitHubOAuthState.created_at < datetime.utcnow() - timedelta(minutes=10),
    ).delete(synchronize_session=False)
    db.add(GitHubOAuthState(
        state_hash=hashlib.sha256(state.encode("utf-8")).hexdigest(),
        user_id=current_user.id,
    ))
    db.commit()
    return {"url": url, "state": state}


@app.post("/api/v1/github/oauth/callback")
def github_oauth_callback(
    payload: GitHubOAuthCallback,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    state_hash = hashlib.sha256(payload.state.encode("utf-8")).hexdigest()
    state = db.query(GitHubOAuthState).filter(
        GitHubOAuthState.state_hash == state_hash,
        GitHubOAuthState.user_id == current_user.id,
        GitHubOAuthState.created_at >= datetime.utcnow() - timedelta(minutes=10),
    ).first()
    if state is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state.")
    db.delete(state)
    db.commit()
    try:
        token = exchange_oauth_code(payload.code, payload.state)
        validate_github_token(token)
        save_user_github_token(db, current_user.id, token)
    except GitHubServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"status": "connected", "provider": "github"}


@app.get("/api/v1/github/oauth/callback")
def github_oauth_browser_callback(
    code: str = Query(..., min_length=1),
    state_value: str = Query(..., alias="state", min_length=1),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    state_hash = hashlib.sha256(state_value.encode("utf-8")).hexdigest()
    state = db.query(GitHubOAuthState).filter(
        GitHubOAuthState.state_hash == state_hash,
        GitHubOAuthState.created_at >= datetime.utcnow() - timedelta(minutes=10),
    ).first()
    if state is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state.")
    user_id = state.user_id
    db.delete(state)
    db.commit()
    try:
        token = exchange_oauth_code(code, state_value)
        validate_github_token(token)
        save_user_github_token(db, user_id, token)
    except GitHubServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return RedirectResponse(url=f"{FRONTEND_URL.rstrip('/')}/repositories?github=connected", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/api/v1/github/repositories")
def github_repositories(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, str]]:
    token = get_user_github_token(db, current_user.id)
    if not token:
        return []
    try:
        return get_github_repositories(token)
    except GitHubServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@app.get("/api/v1/llm/config")
def llm_config(current_user: User = Depends(get_current_user)) -> dict[str, str | bool]:
    del current_user
    return {"configured": groq_configured(), "provider": "groq", "model": groq_model()}


@app.post("/api/v1/repositories", response_model=RepositoryResponse)
def connect_repository(payload: RepositoryCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    repo = db.query(Repository).filter(Repository.user_id == current_user.id, Repository.full_name == payload.full_name).first()
    if repo is None:
        repo = Repository(
            user_id=current_user.id,
            full_name=payload.full_name,
            name=payload.name,
            default_branch=payload.default_branch,
            primary_language=payload.primary_language,
            indexing_status="pending",
        )
        db.add(repo)
        db.commit()
        db.refresh(repo)
    else:
        repo.default_branch = payload.default_branch
        repo.primary_language = payload.primary_language
        repo.indexing_status = "pending"
        db.commit()
        db.refresh(repo)

    return RepositoryResponse(
        id=repo.id,
        user_id=repo.user_id,
        github_repo_id=repo.github_repo_id,
        full_name=repo.full_name,
        name=repo.name,
        default_branch=repo.default_branch,
        primary_language=repo.primary_language,
        indexing_status=repo.indexing_status,
        created_at=repo.created_at,
    )


@app.post("/api/v1/repositories/connect", response_model=RepositoryResponse)
def connect_repository_alias(payload: RepositoryCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    return connect_repository(payload, current_user, db)


@app.get("/api/v1/repositories/{repository_id}", response_model=RepositoryResponse)
def get_repository(repository_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RepositoryResponse:
    repo = db.query(Repository).filter(Repository.id == repository_id, Repository.user_id == current_user.id).first()
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    return RepositoryResponse(
        id=repo.id,
        user_id=repo.user_id,
        github_repo_id=repo.github_repo_id,
        full_name=repo.full_name,
        name=repo.name,
        default_branch=repo.default_branch,
        primary_language=repo.primary_language,
        indexing_status=repo.indexing_status,
        created_at=repo.created_at,
    )


@app.get("/api/v1/repositories/{repository_id}/structure", response_model=RepositoryStructureResponse)
def repository_structure(repository_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RepositoryStructureResponse:
    repo = db.query(Repository).filter(Repository.id == repository_id, Repository.user_id == current_user.id).first()
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    try:
        token = get_user_github_token(db, current_user.id)
        return RepositoryStructureResponse(
            repository_id=repo.id,
            full_name=repo.full_name,
            branch=repo.default_branch,
            files=repo_structure_for(repo.full_name, token, repo.default_branch),
        )
    except GitHubServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@app.get("/api/v1/dashboard", response_model=DashboardResponse)
def dashboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DashboardResponse:
    total_tasks = db.query(Task).filter(Task.user_id == current_user.id).count()
    completed_tasks = db.query(Task).filter(Task.user_id == current_user.id, Task.status == "completed").count()
    active_tasks = db.query(Task).filter(
        Task.user_id == current_user.id,
        Task.status.in_(["queued", "analyzing", "planning", "coding", "testing", "debugging", "reviewing"]),
    ).order_by(Task.updated_at.desc()).all()
    in_progress_tasks = len(active_tasks)
    repositories = db.query(Repository).filter(Repository.user_id == current_user.id).count()
    return DashboardResponse(
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        in_progress_tasks=in_progress_tasks,
        repositories=repositories,
        agent_status=active_tasks[0].current_agent if active_tasks else "idle",
    )


@app.get("/api/v1/phases", response_model=PhaseReport)
def phase_status() -> PhaseReport:
    return PhaseReport(
        phases=[
            PhaseStatus(
                phase=item["phase"],
                name=item["name"],
                description=item["description"],
                status=item["status"],
                completed=item["status"] == "completed",
            )
            for item in PHASES
        ]
    )


@app.post("/api/v1/tasks", response_model=TaskResponse)
def create_task(payload: TaskCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TaskResponse:
    repo = db.query(Repository).filter(Repository.id == payload.repository_id, Repository.user_id == current_user.id).first()
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    task = Task(
        user_id=current_user.id,
        repository_id=repo.id,
        title=payload.title,
        description=payload.description,
        status="queued",
        priority=payload.priority,
        base_branch=payload.base_branch or repo.default_branch,
        current_agent="repository_analyzer",
        feature_branch=f"ase/task-{secrets.token_hex(4)}",
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    emit_task_event(task.id, "task_created", "Task created and queued for repository analysis.", title=task.title)
    emit_task_event(task.id, "task_queued", "Task is queued for Groq-backed repository analysis.", status="queued")

    return TaskResponse(
        id=task.id,
        user_id=task.user_id,
        repository_id=task.repository_id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        base_branch=task.base_branch,
        feature_branch=task.feature_branch,
        current_agent=task.current_agent,
        retry_count=task.retry_count,
        approval_status=task.approval_status,
        diff=task.diff,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@app.get("/api/v1/tasks", response_model=list[TaskResponse])
def list_tasks(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[TaskResponse]:
    tasks = db.query(Task).filter(Task.user_id == current_user.id).order_by(Task.created_at.desc()).all()
    return [
        TaskResponse(
            id=task.id,
            user_id=task.user_id,
            repository_id=task.repository_id,
            title=task.title,
            description=task.description,
            status=task.status,
            priority=task.priority,
            base_branch=task.base_branch,
            feature_branch=task.feature_branch,
            current_agent=task.current_agent,
            retry_count=task.retry_count,
            approval_status=task.approval_status,
            diff=task.diff,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


@app.get("/api/v1/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TaskResponse:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    return TaskResponse(
        id=task.id,
        user_id=task.user_id,
        repository_id=task.repository_id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        base_branch=task.base_branch,
        feature_branch=task.feature_branch,
        current_agent=task.current_agent,
        retry_count=task.retry_count,
        approval_status=task.approval_status,
        diff=task.diff,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@app.get("/api/v1/tasks/{task_id}/workflow", response_model=WorkflowStatusResponse)
def get_task_workflow(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> WorkflowStatusResponse:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    workflow = workflow_steps_for_task(task)
    return WorkflowStatusResponse(
        task_id=task.id,
        status=task.status,
        current_agent=task.current_agent,
        steps=[
            {
                "id": step["id"],
                "name": step["name"],
                "description": step["description"],
                "status": step["status"],
                "current": step["current"],
            }
            for step in workflow
        ],
    )


@app.post("/api/v1/tasks/{task_id}/workflow/run", response_model=WorkflowStatusResponse)
def run_task_workflow(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> WorkflowStatusResponse:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot run a workflow for a {task.status} task.")
    if task.current_agent == "validator":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run validation before continuing to the reviewer.")
    if task.current_agent == "reviewer":
        existing_review = db.query(EventLog).filter(
            EventLog.task_id == task.id,
            EventLog.event_type == "agent_completed",
        ).order_by(EventLog.created_at.desc()).first()
        if (
            existing_review
            and json.loads(existing_review.payload or "{}").get("agent") == "reviewer"
            and json.loads(existing_review.payload or "{}").get("retry_count", 0) == task.retry_count
        ):
            return get_task_workflow(task_id, current_user, db)

    repo = db.query(Repository).filter(
        Repository.id == task.repository_id,
        Repository.user_id == current_user.id,
    ).first()
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    task_input = {"title": task.title, "description": task.description}
    result: str | None = None
    coder_output: str | None = None
    patch_attempts: list[dict[str, Any]] = []
    completion_metadata: list[dict[str, Any]] = []
    try:
        github_token = get_user_github_token(db, current_user.id)
        if not github_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Connect a GitHub account before running repository agents.")
        context = get_repository_context(repo.full_name, task.base_branch or repo.default_branch, github_token)
        prior_events = db.query(EventLog).filter(EventLog.task_id == task.id).order_by(EventLog.created_at.asc()).all()
        prior_results = "\n\n".join(
            f"{json.loads(event.payload or '{}').get('agent', event.event_type)}:\n"
            f"{json.loads(event.payload or '{}').get('result', '')}"
            f"{json.dumps(json.loads(event.payload or '{}'), ensure_ascii=False) if event.event_type.startswith('validation_') else ''}"
            for event in prior_events
            if event.event_type == "agent_completed" or event.event_type.startswith("validation_")
        )
        result = generate_agent_output(
            task.current_agent,
            task_input,
            context,
            prior_results,
        )
        completion_metadata = getattr(result, "completion_metadata", [])
        if task.current_agent == "coder":
            coder_output = getattr(result, "raw_output", result)
            for attempt in range(3):
                generated_patch = ""
                try:
                    generated_patch = build_patch_from_edits(
                        repo.full_name,
                        task.base_branch or repo.default_branch,
                        github_token,
                        result,
                    )
                    patch_error = check_patch_applies(
                        repo.full_name,
                        task.base_branch or repo.default_branch,
                        github_token,
                        generated_patch,
                    )
                except CoderEditError as exc:
                    patch_error = str(exc)
                patch_attempts.append({
                    "attempt": attempt + 1,
                    "patch": getattr(result, "raw_output", result),
                    "error": patch_error or "",
                    "generated_diff": generated_patch,
                    "completion_metadata": completion_metadata,
                })
                if patch_error is None:
                    result = generated_patch
                    break
                if attempt == 2:
                    raise LLMProviderError(
                        f"Groq's structured edits could not be applied after 3 attempts: {patch_error[:2000]}",
                        output=result,
                        diagnostics=patch_error,
                        outputs=[attempt_record["patch"] for attempt_record in patch_attempts],
                        completion_metadata=[
                            attempt_record["completion_metadata"]
                            for attempt_record in patch_attempts
                        ],
                    )

                correction_context = (
                    "STRUCTURED EDIT VALIDATION FAILURE - FIX THIS FIRST.\n"
                    f"Attempt: {attempt + 1} of 3.\n"
                    f"Exact validation error:\n{patch_error[:1500]}\n\n"
                    f"Rejected JSON edits:\n{result[:8000]}\n\n"
                    'Return corrected JSON only in the {"files":[...]} schema. Existing files must use '
                    "unique exact search/replace blocks. For new files, provide full content. Do not return "
                    "unified diff syntax or explanatory text."
                )
                result = generate_agent_output(
                    "coder",
                    task_input,
                    context,
                    correction_context,
                )
                completion_metadata = getattr(result, "completion_metadata", [])
                coder_output = getattr(result, "raw_output", result)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except LLMProviderError as exc:
        if task.current_agent == "coder":
            unrecorded_outputs = exc.outputs if len(patch_attempts) < 3 else []
            failed_attempts = patch_attempts + [
                {
                    "attempt": len(patch_attempts) + index + 1,
                    "patch": output[:100_000],
                    "error": exc.diagnostics or str(exc),
                    "completion_metadata": (
                        exc.completion_metadata[index]
                        if index < len(exc.completion_metadata)
                        else {}
                    ),
                }
                for index, output in enumerate(unrecorded_outputs)
            ]
            emit_task_event(
                task.id,
                "agent_failed",
                str(exc),
                agent=task.current_agent,
                result=(exc.output or result or "")[:100_000],
                patch_attempts=failed_attempts,
                retry_count=task.retry_count,
            )
        else:
            emit_task_event(task.id, "agent_failed", str(exc), agent=task.current_agent)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except GitHubServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if task.current_agent == "coder":
        if len(result) > 100_000 or not (result.startswith("diff --git ") or result.startswith("--- ")):
            emit_task_event(task.id, "agent_failed", "Coder did not return a valid unified diff.", agent="coder")
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Groq did not return a valid unified diff.")
        task.diff = result

    agent = task.current_agent
    emit_task_event(
        task.id,
        "agent_completed",
        f"{agent.replace('_', ' ').title()} agent completed.",
        agent=agent,
        result=result,
        retry_count=task.retry_count,
        **(
            {
                "model_output": coder_output,
                "patch_attempts": patch_attempts,
                "completion_metadata": completion_metadata,
            }
            if agent == "coder"
            else {}
        ),
    )
    if agent == "reviewer":
        task.status = "reviewing"
        task.approval_status = "pending"
    else:
        next_step = next_workflow_step(task)
        if next_step is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No next workflow stage is available.")
        task.status = next_step["status"]
        task.current_agent = next_step["id"]
    task.updated_at = datetime.utcnow()
    db.commit()
    return get_task_workflow(task_id, current_user, db)


@app.get("/api/v1/tasks/{task_id}/events")
async def task_events(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> StreamingResponse:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    logs = db.query(EventLog).filter(EventLog.task_id == task_id).order_by(EventLog.created_at.asc()).all()
    history = [
        {
            "event": log.event_type,
            "task_id": task_id,
            "message": log.message,
            "payload": json.loads(log.payload) if log.payload else {},
            "timestamp": log.created_at.isoformat(),
        }
        for log in logs
    ]

    async def event_generator():
        for item in history:
            yield f"event: {item['event']}\ndata: {json.dumps(item)}\n\n"
        await asyncio.sleep(0.1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/v1/tasks/{task_id}/logs", response_model=TaskLogResponse)
def task_logs(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TaskLogResponse:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    logs = db.query(EventLog).filter(EventLog.task_id == task_id).order_by(EventLog.created_at.asc()).all()
    return TaskLogResponse(
        task_id=task.id,
        events=[{"event": log.event_type, "message": log.message, "payload": json.loads(log.payload) if log.payload else {}, "timestamp": log.created_at.isoformat()} for log in logs],
    )


@app.get("/api/v1/tasks/{task_id}/diff")
def task_diff(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    return {"task_id": task.id, "diff": task.diff or ""}


@app.post("/api/v1/tasks/{task_id}/start")
def start_task(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.status != "queued":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only queued tasks can be started.")
    task.status = "analyzing"
    task.current_agent = "repository_analyzer"
    db.commit()
    emit_task_event(task.id, "agent_started", "Repository analysis started.", agent="repository_analyzer")
    return {"status": "analyzing", "task_id": task.id}


@app.post("/api/v1/tasks/{task_id}/execute", response_model=ExecutionResult)
def execute_task(
    task_id: str,
    payload: ExecutionRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExecutionResult:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    repo = db.query(Repository).filter(Repository.id == task.repository_id, Repository.user_id == current_user.id).first()
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    if not task.diff:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run the coder agent before validation.")
    if task.current_agent != "validator" or task.status not in {"testing", "queued", "failed"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task is not waiting for validation.")

    command = (payload.command if payload and payload.command else default_command_for_repo(repo.full_name, repo.primary_language)).strip()
    workspace_root = _project_root() / ".workspaces" / current_user.id / f"{task.id}-{task.retry_count}"
    try:
        github_token = get_user_github_token(db, current_user.id)
        if not github_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Connect a GitHub account before validating a task.")
        download_repository(repo.full_name, task.base_branch or repo.default_branch, github_token, workspace_root)
        patch_marker = workspace_root / ".ase-patch-applied"
        if not patch_marker.exists():
            check = subprocess.run(
                ["git", "apply", "--check", "--whitespace=fix", "-"],
                cwd=str(workspace_root),
                input=task.diff,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if check.returncode:
                detail = f"Generated patch does not apply: {check.stderr.strip()}"
                task.status = "failed"
                task.current_agent = "coder"
                task.updated_at = datetime.utcnow()
                db.commit()
                emit_task_event(
                    task.id,
                    "validation_failed",
                    detail,
                    success=False,
                    retry_count=task.retry_count,
                )
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
            applied = subprocess.run(
                ["git", "apply", "--whitespace=fix", "-"],
                cwd=str(workspace_root),
                input=task.diff,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if applied.returncode:
                detail = f"Unable to apply generated patch: {applied.stderr.strip()}"
                task.status = "failed"
                task.current_agent = "coder"
                task.updated_at = datetime.utcnow()
                db.commit()
                emit_task_event(
                    task.id,
                    "validation_failed",
                    detail,
                    success=False,
                    retry_count=task.retry_count,
                )
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
            patch_marker.write_text("applied", encoding="utf-8")
    except GitHubServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    try:
        result = run_local_command(task.id, command, cwd=workspace_root, timeout_seconds=(payload.timeout_seconds if payload else 120))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ExecutionError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        result = {
            "task_id": task.id,
            "command": command,
            "exit_code": 124,
            "success": False,
            "stdout": stdout,
            "stderr": stderr + "\nCommand timed out in execution container.",
            "duration_ms": 0,
            "working_directory": str(workspace_root),
            "created_at": datetime.utcnow().isoformat(),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Docker is required to run isolated validation.") from exc

    task.status = "reviewing" if result["success"] else "failed"
    task.current_agent = "reviewer" if result["success"] else "validator"
    db.commit()
    emit_task_event(
        task.id,
        "validation_completed" if result["success"] else "validation_failed",
        f"Container validation finished with exit code {result['exit_code']}.",
        command=command,
        exit_code=result["exit_code"],
        success=result["success"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        retry_count=task.retry_count,
    )

    return ExecutionResult(
        task_id=str(result["task_id"]),
        command=str(result["command"]),
        exit_code=int(result["exit_code"]),
        success=bool(result["success"]),
        stdout=str(result["stdout"]),
        stderr=str(result["stderr"]),
        duration_ms=int(result["duration_ms"]),
        working_directory=str(result["working_directory"]),
        created_at=result["created_at"],
    )


@app.post("/api/v1/tasks/{task_id}/cancel")
def cancel_task(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot cancel a {task.status} task.")
    task.status = "cancelled"
    db.commit()
    emit_task_event(task.id, "task_cancelled", "Task was cancelled by the user.", status="cancelled")
    return {"status": "cancelled", "task_id": task.id}


@app.post("/api/v1/tasks/{task_id}/skip-validation")
def skip_validation(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if not task.diff:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Generate a patch before skipping validation.")
    if task.current_agent != "validator" or task.status not in {"testing", "failed"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Validation can only be skipped while the task is waiting for validation.")

    task.status = "reviewing"
    task.current_agent = "reviewer"
    task.updated_at = datetime.utcnow()
    db.commit()
    emit_task_event(
        task.id,
        "validation_skipped",
        "Validation was explicitly skipped by the user; tests were not run.",
        success=False,
        skipped=True,
        reason="User chose to proceed without Docker validation.",
        retry_count=task.retry_count,
    )
    return {"status": "skipped", "task_id": task.id}


@app.post("/api/v1/tasks/{task_id}/retry")
def retry_task(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed or cancelled tasks can be retried.")
    task.status = "queued"
    task.retry_count += 1
    task.current_agent = "repository_analyzer"
    task.approval_status = "pending"
    task.diff = None
    task.feature_branch = f"ase/task-{secrets.token_hex(4)}"
    db.commit()
    emit_task_event(task.id, "task_queued", "Task retried after a failure or cancellation.", status="queued", retry_count=task.retry_count)
    return {"status": "queued", "task_id": task.id}


@app.get("/api/v1/repositories/{repository_id}/index-status")
def repository_index_status(repository_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    repo = db.query(Repository).filter(Repository.id == repository_id, Repository.user_id == current_user.id).first()
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    message = (
        f"Repository {repo.full_name} is indexed and ready."
        if repo.indexing_status == "ready"
        else f"Repository {repo.full_name} has not been indexed yet."
    )
    return {"repository_id": repo.id, "status": repo.indexing_status, "message": message}


@app.post("/api/v1/repositories/{repository_id}/index", response_model=RepositoryIndexResponse)
def repository_index(repository_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RepositoryIndexResponse:
    repo = db.query(Repository).filter(Repository.id == repository_id, Repository.user_id == current_user.id).first()
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    try:
        github_token = get_user_github_token(db, current_user.id)
        if not github_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Connect a GitHub account before indexing repositories.")
        files = repo_structure_for(repo.full_name, github_token, repo.default_branch)
    except GitHubServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    repo.indexing_status = "ready" if files else "failed"
    db.commit()
    return RepositoryIndexResponse(
        repository_id=repo.id,
        status=repo.indexing_status,
        message=f"Indexed {len(files)} source paths for {repo.full_name}.",
    )


@app.post("/api/v1/tasks/{task_id}/approve")
def approve_task(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    validations = db.query(EventLog).filter(
        EventLog.task_id == task.id,
        EventLog.event_type == "validation_completed",
    ).order_by(EventLog.created_at.desc()).all()
    reviews = db.query(EventLog).filter(
        EventLog.task_id == task.id,
        EventLog.event_type == "agent_completed",
    ).all()
    validation_passed = any(
        json.loads(item.payload or "{}").get("success")
        and json.loads(item.payload or "{}").get("retry_count", 0) == task.retry_count
        for item in validations
    )
    validation_skipped = db.query(EventLog).filter(
        EventLog.task_id == task.id,
        EventLog.event_type == "validation_skipped",
    ).order_by(EventLog.created_at.desc()).all()
    has_current_skip = any(
        json.loads(item.payload or "{}").get("skipped") is True
        and json.loads(item.payload or "{}").get("retry_count", 0) == task.retry_count
        for item in validation_skipped
    )
    if task.status != "reviewing" or not (validation_passed or has_current_skip):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task must pass validation or have it explicitly skipped, and reach review before approval.")
    if not any(
        json.loads(review.payload or "{}").get("agent") == "reviewer"
        and json.loads(review.payload or "{}").get("retry_count", 0) == task.retry_count
        for review in reviews
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The reviewer agent must finish before approval.")
    task.status = "completed"
    task.approval_status = "approved"
    task.current_agent = "github_pr"
    db.commit()
    emit_task_event(task.id, "approval_granted", "Task approved by the user. Draft PR publishing is now enabled.", status="completed")
    return {"status": "completed", "task_id": task.id}


@app.post("/api/v1/tasks/{task_id}/pull-request", response_model=PullRequestResponse)
def create_pull_request(task_id: str, payload: PullRequestCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PullRequestResponse:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    repo = db.query(Repository).filter(Repository.id == task.repository_id, Repository.user_id == current_user.id).first()
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    if task.approval_status != "approved" or task.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approve the reviewed task before creating a pull request.")
    existing_pr = db.query(PullRequest).filter(PullRequest.task_id == task.id).first()
    if existing_pr is not None:
        return PullRequestResponse(
            id=existing_pr.id,
            task_id=existing_pr.task_id,
            repository_id=existing_pr.repository_id,
            title=existing_pr.title,
            head_branch=existing_pr.head_branch,
            base_branch=existing_pr.base_branch,
            status=existing_pr.status,
            body=existing_pr.body,
            url=existing_pr.url,
            created_at=existing_pr.created_at,
        )
    if not task.diff:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The task has no generated patch.")
    head_branch = payload.head_branch or task.feature_branch
    base_branch = payload.base_branch or task.base_branch or repo.default_branch
    if not head_branch or head_branch == base_branch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pull request head and base branches must differ.")
    try:
        github_token = get_user_github_token(db, current_user.id)
        if not github_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Connect a GitHub account before creating a pull request.")
        skipped_validation = any(
            json.loads(event.payload or "{}").get("skipped") is True
            and json.loads(event.payload or "{}").get("retry_count", 0) == task.retry_count
            for event in db.query(EventLog).filter(
                EventLog.task_id == task.id,
                EventLog.event_type == "validation_skipped",
            ).all()
        )
        validation_summary = (
            "Skipped by user; automated tests were not run."
            if skipped_validation
            else "Container validation passed."
        )
        pr_body = (payload.body or f"## Summary\n\n{task.description}").rstrip()
        pr_body += f"\n\n## Validation\n\n{validation_summary}"
        publish_patch_as_branch(
            repo.full_name,
            base_branch,
            head_branch,
            github_token,
            task.diff,
        )
        remote_pr = create_github_pull_request(
            repo.full_name,
            github_token,
            title=payload.title,
            head=head_branch,
            base=base_branch,
            body=pr_body,
        )
    except GitHubServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    pr = PullRequest(
        task_id=task.id,
        repository_id=repo.id,
        title=payload.title,
        head_branch=head_branch,
        base_branch=base_branch,
        status="draft",
        body=pr_body,
        url=remote_pr["html_url"],
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    emit_task_event(task.id, "pull_request_created", f"Draft PR #{remote_pr['number']} created for {repo.full_name}.", pr_id=pr.id, url=pr.url, head_branch=pr.head_branch, base_branch=pr.base_branch)
    return PullRequestResponse(
        id=pr.id,
        task_id=pr.task_id,
        repository_id=pr.repository_id,
        title=pr.title,
        head_branch=pr.head_branch,
        base_branch=pr.base_branch,
        status=pr.status,
        body=pr.body,
        url=pr.url,
        created_at=pr.created_at,
    )


@app.get("/api/v1/repositories/{repository_id}/pull-requests", response_model=list[PullRequestResponse])
def list_pull_requests(repository_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[PullRequestResponse]:
    repo = db.query(Repository).filter(Repository.id == repository_id, Repository.user_id == current_user.id).first()
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    prs = db.query(PullRequest).filter(PullRequest.repository_id == repo.id).order_by(PullRequest.created_at.desc()).all()
    return [
        PullRequestResponse(
            id=pr.id,
            task_id=pr.task_id,
            repository_id=pr.repository_id,
            title=pr.title,
            head_branch=pr.head_branch,
            base_branch=pr.base_branch,
            status=pr.status,
            body=pr.body,
            url=pr.url,
            created_at=pr.created_at,
        )
        for pr in prs
    ]


@app.post("/api/v1/tasks/{task_id}/reject")
def reject_task(task_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.status != "reviewing":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only tasks in review can be rejected.")
    task.status = "failed"
    task.approval_status = "rejected"
    db.commit()
    emit_task_event(task.id, "task_failed", "Task was rejected and returned for revision.", status="failed")
    return {"status": "failed", "task_id": task.id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
