# API documentation

Authenticated endpoints use `Authorization: Bearer <access_token>`.

## Authentication and configuration

- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/users/me`
- `GET /api/v1/health`
- `GET /api/v1/llm/config` — Groq availability and selected model; never returns the API key.

## GitHub and repositories

- `POST /api/v1/github/token` — verifies and encrypts the current user's PAT.
- `GET /api/v1/github/config`
- `GET /api/v1/github/oauth/url` — creates a single-use OAuth state and returns an authorization URL.
- `GET /api/v1/github/oauth/callback` — OAuth App callback; encrypts the returned credential.
- `GET /api/v1/github/repositories`
- `GET /api/v1/repositories`, `POST /api/v1/repositories`
- `GET /api/v1/repositories/{repository_id}`
- `GET /api/v1/repositories/{repository_id}/structure`
- `POST /api/v1/repositories/{repository_id}/index`
- `GET /api/v1/repositories/{repository_id}/index-status`

GitHub tokens are user-scoped. OAuth requires a configured OAuth App; a PAT is an alternative.

## Tasks and workflow

- `POST /api/v1/tasks`, `GET /api/v1/tasks`, `GET /api/v1/tasks/{task_id}`
- `POST /api/v1/tasks/{task_id}/start`
- `GET /api/v1/tasks/{task_id}/workflow`
- `POST /api/v1/tasks/{task_id}/workflow/run` — executes the current analyzer, planner, coder, or reviewer stage.
- `POST /api/v1/tasks/{task_id}/execute` — applies the generated diff to a fetched repository snapshot and validates it in Docker. Optional JSON body: `{"command": "python -m pytest -q", "timeout_seconds": 120}`.
- `POST /api/v1/tasks/{task_id}/skip-validation` — explicitly records that validation was skipped and moves the task to review; it does not mark tests as passed.
- `GET /api/v1/tasks/{task_id}/diff`
- `GET /api/v1/tasks/{task_id}/logs`
- `GET /api/v1/tasks/{task_id}/events` — persisted event stream; task ownership is checked.
- `POST /api/v1/tasks/{task_id}/approve` — only after passing validation or explicitly skipping it, and after reviewer completion.
- `POST /api/v1/tasks/{task_id}/reject`
- `POST /api/v1/tasks/{task_id}/retry`
- `POST /api/v1/tasks/{task_id}/cancel`

## Draft pull requests

- `POST /api/v1/tasks/{task_id}/pull-request` — publishes the generated patch to a task branch and creates a GitHub draft PR. Requires successful validation or an explicit validation skip, reviewer completion, and explicit task approval. The PR body identifies when validation was skipped. Request fields: `title`, optional `head_branch`, `base_branch`, and `body`.
- `GET /api/v1/repositories/{repository_id}/pull-requests`

External-provider errors are returned as non-success HTTP responses; credentials and provider secrets are not included in responses.
