# ctx

`ctx` is a local-first context manager for AI-assisted development workflows.

It helps you track which project is active, where it should be continued, which AI agent and provider are relevant, and what the next single action is.

It does not configure Codex, Claude Code, CC Switch, providers, credentials, proxies, or Git remotes. It only records, checks, reminds, and helps you avoid context loss.

## Install

From this repository, you can run `ctx` without installing it globally:

```bash
uv run ctx --help
uv run ctx --data-dir samples/ledger now
```

To install the `ctx` command for regular use:

```bash
python3 -m pip install --user -e .
ctx --help
```

If `ctx` is still not found after installing with `--user`, make sure
`~/.local/bin` is on your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
ctx --help
```

For development, install the dev extras:

```bash
python3 -m pip install -e ".[dev]"
```

Run tests:

```bash
UV_CACHE_DIR=/tmp/local-ai-ctx-uv-cache uv run --extra dev pytest -q
```

## Data Directory

`ctx` reads two YAML files from a ledger directory:

```text
projects.yml
providers.yml
```

Resolution order:

1. `--data-dir`
2. `CTX_LEDGER_DIR`
3. `~/.local/share/ctx/ledger`

For daily use, point `ctx` at your private ledger directory:

```bash
export CTX_LEDGER_DIR=/mnt/d/ai-workbench-ledger
ctx init
ctx add my-project --status doing --next-action "Decide the next single action"
ctx now
```

If you have not installed the `ctx` command yet, use `uv run ctx` from this
repository:

```bash
export CTX_LEDGER_DIR=/mnt/d/ai-workbench-ledger
uv run ctx init
uv run ctx add my-project --status doing --next-action "Decide the next single action"
uv run ctx now
```

Use `--data-dir` for one-off overrides or to try the sample data:

```bash
uv run ctx --data-dir samples/ledger now
uv run ctx --data-dir samples/ledger list
uv run ctx --data-dir samples/ledger show client-portal-demo
uv run ctx --data-dir samples/ledger next
uv run ctx --data-dir samples/ledger doctor
```

## Common Operations

Use a private ledger outside this repository:

```bash
export CTX_LEDGER_DIR=/mnt/d/ai-workbench-ledger
```

Initialize the ledger:

```bash
ctx init
```

Add a project:

```bash
ctx add local-ai-ctx --status doing --priority high --next-action "Write the next handoff note"
```

Check what to work on now:

```bash
ctx now
ctx next
```

Inspect projects:

```bash
ctx list
ctx show local-ai-ctx
```

Check ledger consistency:

```bash
ctx doctor
```

Run the same commands without installing `ctx` by prefixing them with `uv run`:

```bash
uv run ctx doctor
uv run ctx --data-dir samples/ledger now
```

## Supported Commands

```bash
ctx init
ctx add <project-id> --next-action "<next action>"
ctx now
ctx list
ctx show <project>
ctx next
ctx doctor
```

`ctx init` creates an empty ledger directory with `projects.yml` and `providers.yml`. It does not overwrite existing files.

`ctx add` creates a minimal project entry. It requires a project id and next action, and defaults to `todo` status and `medium` priority.

`ctx doctor` checks ledger consistency. It is read-only, exits non-zero for errors, and reports warnings without blocking.

This first MVP only writes through `init` and `add`. It does not run Git checks, write handoffs, modify provider settings, read secrets, or perform push, merge, rebase, or provider switching.

Keep personal ledger files outside this repository. The files in `samples/ledger` are synthetic examples for documentation and tests.

## Visual Editing

`ctx` keeps `projects.yml` and `providers.yml` as the source of truth, so third-party tools can edit the same files as the CLI.

The stable schema contract lives in:

```text
schemas/projects.schema.json
schemas/providers.schema.json
```

With the VS Code YAML extension, these schemas provide field completion, enum suggestions, required-field validation, and type errors. This repository includes `.vscode/settings.json` for the sample ledger.

For a private ledger workspace, add a VS Code workspace setting like:

```json
{
  "yaml.schemas": {
    "/absolute/path/to/local-ai-ctx/schemas/projects.schema.json": [
      "projects.yml",
      "**/projects.yml"
    ],
    "/absolute/path/to/local-ai-ctx/schemas/providers.schema.json": [
      "providers.yml",
      "**/providers.yml"
    ]
  }
}
```

Schema validation is intentionally single-file. Cross-file checks such as unknown provider references belong in `ctx doctor`.

## YAML Shape

Minimal `projects.yml`:

```yaml
projects:
  example:
    name: example
    status: doing
    priority: medium
    surfaces:
      wsl:
        path: /mnt/d/dev/example
    agents:
      - codex-cli
    providers:
      - official
    next_action: Decide the next single action
```

Minimal `providers.yml`:

```yaml
providers:
  official:
    type: official
    managed_by:
      - login
    scope:
      surfaces: [host, wsl]
      agents: [codex-cli, codex-desktop]
```
