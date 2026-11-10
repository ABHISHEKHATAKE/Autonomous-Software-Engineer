# Testing

## Backend

From the repository root:

```powershell
python -m compileall -q backend\app backend\tests
python -m pytest backend\tests -q
```

Tests mock Groq, GitHub, and Docker API boundaries; they do not require external service credentials or a running Docker daemon.

## Frontend

```powershell
Set-Location frontend
npm run build
```

## Manual integration check

Set `GROQ_API_KEY`, connect a GitHub account, and ensure the backend can access Docker and the configured `EXECUTION_IMAGE`. Create a task on a disposable repository, run each agent, inspect the diff, validate it, inspect the reviewer output, and approve before creating a draft PR.
