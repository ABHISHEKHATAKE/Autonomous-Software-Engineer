# Groq Coding Output Troubleshooting

## Issue

The coding stage has failed with either:

- `Groq generated a patch that does not apply ... error: corrupt patch at line N`
- `Groq could not produce a valid unified diff`

These indicate a generated-output problem, not necessarily a bug in the existing repository source.

## What we have verified

- One reported patch was truncated: its hunk declared 21 added lines but contained only 20, and the C++ function’s closing brace was missing.
- A later multi-file patch passed a local Git check. Git’s `--recount` option also caused a valid patch to be rejected and was removed.
- Unified-diff generation has been replaced with structured JSON file operations: create a file, delete a file, or edit an existing file using an exact search/replace block. The backend applies those operations to the selected repository snapshot and asks Git to generate the unified diff.
- The backend rejects a search block unless it matches exactly once, validates the generated diff against the repository, and retries with the specific error.
- Coder responses now include Groq’s `finish_reason` and token usage in task logs. A response stopped at the token limit is retried rather than accepted.

## How to inspect a failure

1. Rebuild and restart the backend and frontend after code changes:

   ```powershell
   docker compose up --build -d backend frontend
   ```

2. Retry the coding stage.
3. On the task page, expand **Agent and validation output**, then expand each **Groq output** attempt.
4. Preserve the complete JSON output, completion metadata, and corresponding edit-validation error.

The **Diff preview** displays the Git-generated diff after edits are accepted. If coding fails before acceptance, inspect the rejected-output entries in the logs instead.

## Current limitation

The exact cause of a future edit failure can only be identified from the complete rejected JSON output, completion metadata, and matching validation error. Earlier task attempts that predate rejected-output logging were not saved.
