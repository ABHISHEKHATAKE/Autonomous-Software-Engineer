# System architecture

- **Frontend:** React/TypeScript dashboard. API base is configured by `VITE_API_URL`.
- **API:** FastAPI handles accounts, task state, workflow orchestration, and user-scoped GitHub credentials.
- **Database:** SQLAlchemy models; SQLite is the local Compose default.
- **LLM:** `llm_service.py` calls Groq's OpenAI-compatible chat-completions API using `GROQ_API_KEY` and `GROQ_MODEL`.
- **GitHub:** GitHub REST API is used for OAuth/PAT-backed repository discovery, bounded source context, archive download, branch commits, and draft PRs.
- **Execution:** the backend starts a separate Docker container per validation command. It mounts only that task's source snapshot, applies resource constraints, drops capabilities, and defaults to `EXECUTION_NETWORK=none`.

The workflow is explicit: repository analyzer → planner → coder → validator → reviewer → user approval → branch and draft PR. Agent responses, task state, and execution events are persisted. Validation failures do not advance to review, and no branch/PR is published before user approval.

The local Docker worker and application share the Docker daemon. For production, move workers to a separately controlled host or service and restrict daemon access; do not treat container flags alone as a complete hostile-code boundary.
