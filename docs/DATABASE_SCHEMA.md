# Database schema

The SQLAlchemy models currently cover:

- `users`: registered user identity and password hash.
- `repositories`: GitHub repository selected for a task.
- `tasks`: task input, generated plan/diff, review/validation state, and approval metadata.
- `event_logs`: persisted task workflow events.
- `user_credentials`: user-scoped encrypted GitHub credentials.
- `github_oauth_states`: hashed state values for the GitHub OAuth callback; callback validation enforces expiry and single use.
- `pull_requests`: draft PR metadata associated with a task and repository.

The database URL is configurable. SQLite is used for local development; PostgreSQL is recommended for a production deployment. Production deployments should configure migrations, backups, access controls, and a managed secrets/key-rotation procedure before use.
