# AGENTS.md

This repository is a local-first AI development context tool. Its purpose is to prevent context loss
when switching between environments, agents, providers, and Git states. Keep the scope small.

## Hard Constraints

- Do not introduce a frontend framework or build chain.
- Do not introduce a database, login, multi-user mode, remote service, or background daemon.
- Do not implement provider switching.
- Do not handle credentials, tokens, proxies, or provider secrets.
- Do not add a full YAML editor or admin backend.
- Do not replace `projects.yml` and `providers.yml` as the only data sources.
- Do not connect to the GitHub API, auto-push, auto-merge, or auto-switch providers.

## Git Operations

**Banned (mutating):** push, merge, rebase, checkout, branch switching, reset, remote management, fetch.

**Allowed (read-only, used by `ctx check`, `ctx close`, `ctx handoff`):**
- `git rev-parse` — check if inside a work tree, resolve upstream ref
- `git symbolic-ref` — read current branch name
- `git rev-list --count` — count commits ahead/behind upstream
- `git status --porcelain` — count staged, unstaged, and untracked files

All git calls must go through `src/ctx/git_check.py`. No git subprocess calls elsewhere.

## UI Rules

- `ctx ui` stays a Python standard-library HTTP server with inline HTML/CSS and small native JavaScript only.
- The UI is **frozen**: no new features — no filters, charts, mobile layout, theme system, or frontend framework.
- Existing daily controls (search, status filtering, summary cards, expanded editing, status/priority quick changes) are maintained.
- Quick changes must preserve all other project fields, including `next_action`, providers, repo, rules, blockers, risks, surfaces, and agents.

## Data Rules

- `projects.yml` and `providers.yml` are the source of truth.
- CLI commands and the local UI may read and write those files through the store layer.
- Schema files document the stable YAML contract; cross-file checks belong in `ctx doctor`.
