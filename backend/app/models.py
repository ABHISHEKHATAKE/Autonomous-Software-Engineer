from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    tasks: Mapped[list["Task"]] = relationship(back_populates="user")
    credentials: Mapped[list["UserCredential"]] = relationship(back_populates="user")


class UserCredential(Base):
    __tablename__ = "user_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_provider_credential"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="credentials")


class GitHubOAuthState(Base):
    __tablename__ = "github_oauth_states"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    github_repo_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(64), default="main")
    primary_language: Mapped[str] = mapped_column(String(64), default="TypeScript")
    indexing_status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    tasks: Mapped[list["Task"]] = relationship(back_populates="repository")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    base_branch: Mapped[str] = mapped_column(String(64), default="main")
    feature_branch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_agent: Mapped[str] = mapped_column(String(64), default="repository_analyzer")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    approval_status: Mapped[str] = mapped_column(String(32), default="pending")
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="tasks")
    repository: Mapped[Repository] = relationship(back_populates="tasks")


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    head_branch: Mapped[str] = mapped_column(String(128), default="feature/demo")
    base_branch: Mapped[str] = mapped_column(String(128), default="main")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    body: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
