# Security

- Passwords are hashed; API endpoints require bearer authentication and task/repository queries are scoped to the current user.
- GitHub credentials are verified before storage and encrypted per user. Encryption derives from `SECRET_KEY`; rotating that key makes stored credentials unreadable, so users must reconnect.
- GitHub OAuth uses high-entropy, single-use state records with a ten-minute lifetime. Configure a real OAuth App; demo client credentials are not used.
- Task execution uses Docker with dropped Linux capabilities, no-new-privileges, read-only container root, a bounded writable temp filesystem, CPU/memory/PID limits, and network disabled by default.
- Pull requests are created as drafts only after successful validation, reviewer completion, and explicit user approval.
- Repository content, task prompts, generated diffs, and prior agent results are sent to the configured Groq API. Do not connect repositories whose contents you are not authorized to send to that provider.

## Required production precautions

- Set a unique `SECRET_KEY` of at least 32 characters and `ENVIRONMENT=production`. The development key and demo account are for local use only.
- Restrict GitHub OAuth scopes and PAT permissions to only the repositories and actions required.
- Use a dedicated worker machine/service; the local runner shares the backend's Docker daemon and must not be exposed as a hostile-code boundary.
- Keep execution networking disabled unless a controlled dependency setup requires it. If enabling network access, use egress filtering and prevent access to metadata services and internal networks.
- Configure TLS, managed secret storage/rotation, database backups, rate limits, audit retention, monitoring, and environment-specific CORS before public deployment.
