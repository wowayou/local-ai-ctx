# ctx

`ctx` is a local-first context manager for AI-assisted development workflows.

It helps you track which project is active, where it should be continued, which AI agent and provider are relevant, and what the next single action is.

It does not configure Codex, Claude Code, CC Switch, providers, credentials, proxies, or Git remotes. It only records, checks, reminds, and helps you avoid context loss.

## 普通用户快速开始

第一版 Release 面向 Linux/WSL。

1. 从 GitHub Release 下载 `ctx-linux-x86_64.tar.gz`。
2. 解压并进入目录：

```bash
tar -xzf ctx-linux-x86_64.tar.gz
cd ctx-linux-x86_64
```

3. 启动本地网页：

```bash
./ctx ui
```

`ctx ui` 会自动创建默认数据目录 `~/.local/share/ctx/ledger`，启动 `127.0.0.1` 本地页面，并尽量自动打开浏览器。如果没有自动打开，终端会打印一个可以复制到浏览器的 URL。

网页里可以新增项目、修改状态、修改优先级、更新下一步动作。provider、surface、agent、repo 和 rules 在“高级设置”里维护，默认不会打扰日常使用。

备用 CLI：

```bash
./ctx now
./ctx next
./ctx list
./ctx doctor
```

要把数据放到其他目录：

```bash
CTX_LEDGER_DIR=/path/to/ledger ./ctx ui
```

## Developer Install

From this repository, you can run `ctx` without installing it globally:

```bash
uv run ctx --help
uv run ctx --data-dir samples/ledger ui --no-open
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

Run the local UI smoke check before changing or releasing the web UI:

```bash
scripts/ui_smoke.sh
```

The smoke check uses a temporary ledger, starts `ctx ui --no-open --port 0`, verifies the Chinese action board homepage, creates a project through the HTTP form, quick-updates status/priority, checks advanced fields are preserved, and runs `ctx now` plus `ctx doctor`.

## Release Checklist

Before tagging or publishing a release, run the same minimum checks used by CI:

```bash
scripts/release_check.sh
```

Do not release if this command fails. It runs the pytest suite and the local UI smoke check. The pytest suite covers the store, CLI, schemas, doctor, and UI handler behavior; the smoke script covers the real local HTTP path and shared YAML ledger flow.

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

Start the local web UI:

```bash
ctx ui
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
ctx ui
ctx init
ctx add <project-id> --next-action "<next action>"
ctx now
ctx list
ctx show <project>
ctx next
ctx doctor
```

`ctx init` creates an empty ledger directory with `projects.yml` and `providers.yml`. It does not overwrite existing files.

`ctx ui` creates the ledger if needed and starts a local-only web UI on `127.0.0.1`. It keeps `projects.yml` and `providers.yml` as the source of truth.

`ctx add` creates a minimal project entry. It requires a project id and next action, and defaults to `todo` status and `medium` priority.

`ctx doctor` checks ledger consistency. It is read-only, exits non-zero for errors, and reports warnings without blocking.

This first MVP writes through `init`, `add`, and the local UI. It does not run Git checks, write handoffs, read secrets, or perform push, merge, rebase, or provider switching.

Keep personal ledger files outside this repository. The files in `samples/ledger` are synthetic examples for documentation and tests.

## 维护红线

`ctx` 是本地单用户行动看板，不是管理后台。`projects.yml` 和 `providers.yml` 仍是唯一数据源；CLI 和 `ctx ui` 都只读写这两个文件。

不要为这个 MVP 引入前端框架、构建链、数据库、登录、多用户、远程服务、provider switching、Git 操作、凭据处理、完整 YAML 编辑器或后台 daemon。

`ctx ui` 必须继续使用 Python 标准库 HTTP 服务和内嵌 HTML/CSS/少量原生 JS。允许的效率功能是本页搜索、状态筛选、项目摘要卡片、展开编辑，以及 status/priority 快捷修改。

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
