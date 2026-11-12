# Autonomous Software Engineer

Autonomous Software Engineer is a full-stack platform for turning a software task on a GitHub repository into a proposed, tested, and reviewed code change. Its AI-assisted workflow analyzes repository context, plans edits, generates a patch, validates it in Docker, and prepares a GitHub draft pull request only after human approval.

## Features

- **Repository-aware task planning:** Connect a GitHub account, choose a repository, and describe a coding task. The analyzer summarizes relevant source context, and the planner produces a file-specific plan and validation checklist.
- **Structured code changes:** The coder proposes structured file operations. The backend applies those edits to a repository snapshot and uses Git to generate the diff, so the proposed patch reflects the actual changes.
- **Isolated validation:** Apply the patch to a separate source snapshot and run a selected command in a disposable Docker container. The runner applies resource limits and disables network access by default.
- **AI review with human control:** A reviewer considers the patch and validation output. Users can inspect the diff and task history, then approve or reject the change; the reviewer cannot publish changes on the user's behalf.
- **Approval-gated GitHub publishing:** After the required workflow stages and user approval, publish the patch to a task branch and open a draft pull request.
- **Accounts and GitHub credentials:** Register and sign in, connect through a GitHub OAuth App or personal access token, and store credentials encrypted and scoped to the user.
- **Persistent task activity:** Track workflow state, task events, logs, validation output, and generated diffs through the dashboard and API.

## Workflow

```text
Task + GitHub repository
        ↓
Repository analysis → Plan → Code patch → Docker validation → AI review
                                                           ↓
                                              User approval or rejection
                                                           ↓
                                       GitHub task branch + draft PR
```

Validation failures do not count as successful runs, and the application does not publish a branch or pull request before explicit user approval. Validation may be explicitly skipped; in that case, the skip is recorded and identified in the draft pull request.

## Tech stack

- **Frontend:** React, TypeScript, Vite, and Tailwind CSS
- **Backend:** FastAPI and SQLAlchemy
- **Database:** PostgreSQL in Docker Compose; SQLite by default for direct local development
- **AI:** Groq Chat Completions API
- **Integrations:** GitHub OAuth/PAT, GitHub REST API, and Git
- **Validation:** Disposable Docker containers with resource constraints

## Quick start with Docker Compose

1. Copy `.env.example` to `.env`, change `POSTGRES_PASSWORD` to a URL-safe value, and set `GROQ_API_KEY`. To use GitHub OAuth, configure the OAuth client ID and secret and the callback URL from `.env.example`. Alternatively, connect a verified PAT in the dashboard.
2. Start the application:

   ```powershell
   docker compose up --build
   ```

3. Open `http://localhost:5173`, register an account, connect GitHub, and select a repository.
4. Create a task and run the workflow stages. Inspect the generated diff and validation results, then approve or reject the reviewed change.

The local development account `demo@ase.dev` / `password123` is seeded only when `ENVIRONMENT=development`. Use registration for normal development; never expose the development account publicly.

The local Compose backend mounts the host Docker socket to launch task containers. Use this setup only on a trusted development machine. See [Security](docs/SECURITY.md) and [Deployment](docs/DEPLOYMENT.md) before configuring a deployment.

## Local development

- **Backend:** Install dependencies from `backend/requirements.txt`, set `GROQ_API_KEY`, and run `uvicorn app.main:app --reload` from `backend/`. Direct local development uses SQLite by default; set `DATABASE_URL` to a PostgreSQL connection URL to use PostgreSQL instead.
- **Frontend:** Run `npm install` and `npm run dev` from `frontend/`.
- Set `VITE_API_URL` to configure the frontend API base URL.
- Docker must be available to the backend for validation and publishing. Compose builds the default execution image, `ase-backend:local`.

## Testing

From the repository root:

```powershell
python -m compileall -q backend\app backend\tests
python -m pytest backend\tests -q
Set-Location frontend
npm run build
```

The automated backend tests mock the Groq, GitHub, and Docker API boundaries and do not require external service credentials or a running Docker daemon. See the [testing guide](docs/TESTING.md) for a manual integration check.

## Documentation

- [Project overview](docs/PROJECT_OVERVIEW.md)
- [Agent workflows](docs/AGENT_WORKFLOWS.md)
- [API documentation](docs/API_DOCUMENTATION.md)
- [System architecture](docs/SYSTEM_ARCHITECTURE.md)
- [Security](docs/SECURITY.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Development roadmap](docs/DEVELOPMENT_ROADMAP.md)
