# Database schema

The SQLAlchemy models currently cover:

- `users`: registered user identity and password hash.
- `repositories`: GitHub repository selected for a task.
- `tasks`: task input, generated plan/diff, review/validation state, and approval metadata.
- `event_logs`: persisted task workflow events.
- `user_credentials`: user-scoped encrypted GitHub credentials.
- `github_oauth_states`: hashed state values for the GitHub OAuth callback; callback validation enforces expiry and single use.
- `pull_requests`: draft PR metadata associated with a task and repository.

The database URL is configurable. Direct local development defaults to SQLite; Docker Compose uses PostgreSQL with a persistent named volume. The backend uses SQLAlchemy's `create_all` during startup for initial schema creation. Production deployments should configure migrations, backups, access controls, and a managed secrets/key-rotation procedure before use.
