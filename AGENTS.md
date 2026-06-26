# AGENTS.md

This repository is a local-first context ledger and action board. Keep the scope small.

## Hard Constraints

- Do not introduce a frontend framework or build chain.
- Do not introduce a database, login, multi-user mode, remote service, or background daemon.
- Do not implement provider switching.
- Do not run or add Git operations such as push, merge, rebase, branch switching, or remote management.
- Do not handle credentials, tokens, proxies, or provider secrets.
- Do not add a full YAML editor or admin backend.
- Do not replace `projects.yml` and `providers.yml` as the only data sources.

## UI Rules

- `ctx ui` stays a Python standard-library HTTP server with inline HTML/CSS and small native JavaScript only.
- The UI is a Chinese action board for a local single user.
- Daily controls should stay focused on search, status filtering, summary cards, expanded editing, and status/priority quick changes.
- Quick changes must preserve all other project fields, including `next_action`, providers, repo, rules, blockers, risks, surfaces, and agents.

## Data Rules

- `projects.yml` and `providers.yml` are the source of truth.
- CLI commands and the local UI may read and write those files through the store layer.
- Schema files document the stable YAML contract; cross-file checks belong in `ctx doctor`.
