from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    name: str
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(..., min_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserBase


class UserResponse(UserBase):
    id: str
    created_at: datetime


class RepositoryCreate(BaseModel):
    full_name: str = Field(..., min_length=3, max_length=255, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    name: str = Field(..., min_length=1, max_length=255)
    default_branch: str = Field(default="main", min_length=1, max_length=255)
    primary_language: str = "TypeScript"


class RepositoryResponse(BaseModel):
    id: str
    user_id: str
    github_repo_id: str | None = None
    full_name: str
    name: str
    default_branch: str
    primary_language: str
    indexing_status: str
    created_at: datetime


class TaskCreate(BaseModel):
    repository_id: str
    title: str = Field(..., min_length=3)
    description: str = Field(..., min_length=10)
    priority: str = "medium"
    base_branch: str | None = Field(default=None, min_length=1, max_length=255)


class TaskResponse(BaseModel):
    id: str
    user_id: str
    repository_id: str
    title: str
    description: str
    status: str
    priority: str
    base_branch: str
    feature_branch: str | None = None
    current_agent: str
    retry_count: int = 0
    approval_status: str = "pending"
    diff: str | None = None
    created_at: datetime
    updated_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class DashboardResponse(BaseModel):
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    repositories: int
    agent_status: str


class PhaseStatus(BaseModel):
    phase: int
    name: str
    status: str
    description: str
    completed: bool


class PhaseReport(BaseModel):
    phases: list[PhaseStatus]


class WorkflowStepResponse(BaseModel):
    id: str
    name: str
    description: str
    status: str
    current: bool = False


class WorkflowStatusResponse(BaseModel):
    task_id: str
    status: str
    current_agent: str
    steps: list[WorkflowStepResponse]


class ExecutionRequest(BaseModel):
    command: str | None = Field(default=None, max_length=1000)
    timeout_seconds: int = Field(default=120, ge=5, le=300)


class ExecutionResult(BaseModel):
    task_id: str
    command: str
    exit_code: int
    success: bool
    stdout: str
    stderr: str
    duration_ms: int
    working_directory: str
    created_at: datetime


class TaskLogResponse(BaseModel):
    task_id: str
    events: list[dict]


class RepositoryIndexResponse(BaseModel):
    repository_id: str
    status: str
    message: str


class RepositoryStructureResponse(BaseModel):
    repository_id: str
    full_name: str
    branch: str
    files: list[str]


class GitHubTokenRequest(BaseModel):
    token: str = Field(..., min_length=6)


class GitHubOAuthCallback(BaseModel):
    code: str = Field(..., min_length=1)
    state: str = Field(..., min_length=1)


class PullRequestCreate(BaseModel):
    title: str = Field(..., min_length=3)
    head_branch: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._/-]+$")
    base_branch: str | None = Field(default=None, min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._/-]+$")
    body: str | None = None


class PullRequestResponse(BaseModel):
    id: str
    task_id: str
    repository_id: str
    title: str
    head_branch: str
    base_branch: str
    status: str
    body: str
    url: str | None = None
    created_at: datetime
