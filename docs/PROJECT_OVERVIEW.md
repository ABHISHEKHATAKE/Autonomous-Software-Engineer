# Project Overview

Autonomous Software Engineer turns software requirements into a proposed code change, validation results, review, and an approval-gated draft pull request. The application includes a FastAPI backend, a React dashboard, Groq-backed analysis/planning/coding/review stages, GitHub repository access, and disposable Docker-based command validation.

Local development is supported through Docker Compose. The Compose worker uses the host Docker socket and is not a production security boundary. Production use still requires environment-specific worker isolation and egress controls, managed database/secrets, monitoring, backups, and deployment hardening.
