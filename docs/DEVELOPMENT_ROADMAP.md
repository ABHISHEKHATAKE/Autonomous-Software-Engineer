# Development roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Authentication, backend, frontend, and persistence | Complete |
| 2 | GitHub OAuth/PAT, repository discovery, and indexing | Complete |
| 3 | Repository context analysis with Groq | Complete |
| 4 | Groq-backed analysis, planning, coding, and review stages | Complete |
| 5 | Docker-based task validation | Complete for the local worker; production worker isolation remains |
| 6 | Validation gating, reviewer workflow, and human approval | Complete |
| 7 | Approved branch publishing and draft PR creation | Complete |
| 8 | Dashboard, workflow progress, diff, and PR state | Complete |
| 9 | Production operations and deployment hardening | In progress; deployment, monitoring, managed secrets, backups, and isolated worker infrastructure are environment-specific |

Phase status is intentionally not marked fully complete where the implementation still depends on production infrastructure or repository-specific build images.
