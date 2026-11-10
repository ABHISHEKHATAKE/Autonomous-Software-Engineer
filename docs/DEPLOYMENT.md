# Deployment

## Local Compose

1. Copy `.env.example` to `.env`; configure `GROQ_API_KEY`, `SECRET_KEY`, and optionally GitHub OAuth variables.
2. Ensure Docker Desktop/Engine is running.
3. Run `docker compose up --build`.
4. Open the frontend on port 5173. SQLite data persists in the `ase-data` Compose volume.

The backend image is also the default execution image (`ase-backend:local`). `EXECUTION_IMAGE` can point at a custom image with project-specific tooling. The execution network defaults to `none`. Local Compose mounts the Docker socket so the API can start disposable workers; this grants the API container control over the host Docker daemon.

## Production

This Compose configuration is for local development, not a production deployment template. Do not mount the host Docker socket in a public API container. Before production, use a managed database, TLS-terminating ingress, managed secrets, production frontend/backend origins, health checks and monitoring, backups, rate limiting, and controlled dependency installation. Move execution to separate workers with their own restricted Docker daemon and enforced network egress policy. Set `ENVIRONMENT=production` and a unique `SECRET_KEY` (at least 32 characters); the application refuses to start with the development key.

Do not expose the Docker daemon or execute untrusted repository code on the API host.
