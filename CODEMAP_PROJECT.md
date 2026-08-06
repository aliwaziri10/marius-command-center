# CODEMAP.json Project — Status Log

## Goal
Auto-generate a `CODEMAP.json` in this repo, refreshed on every push via a
GitHub Actions workflow, mapping the codebase's structure (functions, what
calls what, DB tables referenced, env vars read). Purpose: let an AI
assistant working via the GitHub API query structure from one small JSON
file instead of fetching and reading many source files every session.

Why this exists instead of using an off-the-shelf tool (e.g. "Graphify"):
Graphify requires local disk access and a terminal (tree-sitter run
locally, results cached to local disk). This project has neither a local
dev environment nor terminal access available to the assistant - only the
GitHub API, the Supabase API, and the assistant's own disposable sandbox
are reachable. So this is a from-scratch, GitHub-Actions-native equivalent
built for that constraint, not a copy of Graphify.

## Design
- New workflow: `.github/workflows/codemap.yml`
- Trigger: on every push to `main`
- Implementation: Python's built-in `ast` module (zero extra dependencies)
  walks all `.py` files in the repo and extracts:
  - every function/method definition (file, name, line, args)
  - call relationships (what each function calls)
  - every Supabase table name referenced (`/rest/v1/<table>` patterns)
  - every `os.environ[...]` / `os.getenv(...)` env var read
- Output: a single `CODEMAP.json` at repo root, committed back
  automatically by the workflow (via `git-auto-commit-action` or an
  equivalent bot commit step)

## Status
- 2026-08-06: plan approved by Ali. Starting build in this repo first
  (most active of his three projects), then porting the same workflow to
  nova-command-center and upgraded-journey once proven here.
- Build in progress this session - see commit history on this file and on
  `.github/workflows/codemap.yml` / the generator script for latest state.

## Resume instructions (if a session ends mid-build)
Check whether `.github/workflows/codemap.yml` and its generator script
already exist in this repo. If they exist, check the latest Actions run
for that workflow to see if it succeeded and produced a valid
`CODEMAP.json`. If not yet present, resume from the Design section above.
