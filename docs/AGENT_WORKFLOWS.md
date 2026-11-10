# Agent workflows

The task runner is a persisted, user-triggered sequence:

1. **Repository analyzer:** reads a bounded set of files from the selected GitHub branch and summarizes relevant code.
2. **Planner:** creates a file-specific plan and validation checklist.
3. **Coder:** returns structured JSON file operations (create, exact search/replace, or delete). The API applies them to a repository snapshot and generates the unified diff with Git, which is stored as the task's proposed patch.
4. **Validator:** applies that patch to a downloaded source snapshot and runs the selected command in a disposable Docker container.
5. **Reviewer:** reviews the patch and validation output. It cannot approve or publish on the user's behalf.
6. **Human approval:** the user approves or rejects the reviewed task.
7. **Publishing:** after approval, the API creates a task branch through the GitHub Git Data API and opens a draft pull request.

Each model call uses the configured Groq model. Source excerpts, task descriptions, structured edit requests, diffs, and prior results are sent to Groq. Coder completion metadata and generated structured edits are recorded in task logs. Provider, GitHub, edit-application, patch-application, and container failures are surfaced as errors; they are not reported as successful stages.
