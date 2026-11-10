# Autonomous Software Engineer

A repository-task platform with a FastAPI API, React dashboard, Groq-backed agents, GitHub integration, isolated validation, and human-approved draft pull requests.

## Stack

- Backend: FastAPI, SQLAlchemy, SQLite (local) / PostgreSQL-compatible models
- Frontend: React, TypeScript, Vite, Tailwind CSS
- LLM: Groq Chat Completions API
- GitHub: OAuth App or personal access token; credentials are encrypted per user
- Validation: Docker execution container with resource limits and configurable network access

## Quick start with Docker Compose

1. Copy `.env.example` to `.env` and set `GROQ_API_KEY`. For GitHub OAuth, also set the OAuth App client ID/secret and use the callback URL shown in `.env.example`. A PAT can be entered in the dashboard instead.
2. Run `docker compose up --build`.
3. Open `http://localhost:5173`, create an account, connect GitHub, and select a repository.
4. Create a task and run each agent stage. Validation is available after the coder produces a patch. Review and approve it before branch publishing and draft PR creation.

The local development account `demo@ase.dev` / `password123` is seeded only when `ENVIRONMENT=development`. Use registration for normal development; never expose the development account publicly.

The local Compose backend mounts the host Docker socket and includes the Docker CLI to launch task containers. After changing the backend image, rebuild it with `docker compose up --build`. This socket is a powerful host permission; use the setup only on a trusted development machine.

## Local development

- Backend: install `backend/requirements.txt`, set `GROQ_API_KEY`, then run `uvicorn app.main:app --reload` from `backend/`.
- Frontend: run `npm install` and `npm run dev` from `frontend/`.
- The API base can be configured with `VITE_API_URL`.
- Docker must be available to the backend for task validation and publishing. The execution image defaults to `ase-backend:local`, built by Compose.

## Workflow

1. The repository analyzer and planner read bounded GitHub source excerpts and send them with the task to Groq.
2. The coder returns structured JSON file operations. The API applies exact edits to a repository snapshot and asks Git to generate the proposed diff; it does not invent a successful result if Groq is unavailable.
3. Validation applies the patch to an isolated repository snapshot and runs the selected command in Docker.
4. The Groq reviewer inspects the patch and validation output. A human must approve before the API creates a task branch and draft PR.

Repository excerpts and task content are sent to Groq. Configure permissions and data handling accordingly. See [Security](docs/SECURITY.md) and [Deployment](docs/DEPLOYMENT.md).

## Current limits

- The Docker runner is a constrained local worker, not a separately managed production worker service. Production should use a dedicated worker host, egress controls, and a hardened execution image.
- Validation can only use tools/dependencies present in `EXECUTION_IMAGE`. The default image includes Python, pytest, Git, and Node/npm; repository-specific dependencies require a prepared image or an explicitly configured worker setup.
- Deployment is not performed by this project setup. Production database, secrets management, monitoring, backups, and worker isolation still require environment-specific configuration.

See the [roadmap](docs/DEVELOPMENT_ROADMAP.md), [API documentation](docs/API_DOCUMENTATION.md), and [testing guide](docs/TESTING.md).
