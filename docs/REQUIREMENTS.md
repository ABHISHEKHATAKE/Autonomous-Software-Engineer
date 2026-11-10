# Requirements and implementation status

The application supports the core workflow:

- User registration and authentication.
- GitHub OAuth App authorization or personal access token setup, followed by repository selection.
- Groq-powered repository analysis, task planning, unified-diff generation, and review.
- Patch application and configured validation command execution in a constrained, disposable Docker container.
- Human review and explicit approval before a GitHub branch and draft pull request are created.
- Task ownership checks, persisted workflow state, error reporting, retry, and cancellation.

Configuration requires a Groq API key and a `SECRET_KEY`. GitHub publishing additionally requires user-authorized GitHub credentials. External provider calls require network access and valid credentials.

The current Compose configuration is intended for local development only. Production readiness still requires a hardened isolated worker service, network egress policy, production database and secret management, GitHub App installation authentication where needed, continuous event delivery, monitoring, backups, and a deployment-specific security review.
