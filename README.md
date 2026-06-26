# ctx

`ctx` is a local-first context manager for AI-assisted development workflows.

It helps you track which project is active, where it should be continued, which AI agent and provider are relevant, and what the next single action is.

It does not configure Codex, Claude Code, CC Switch, providers, credentials, proxies, or Git remotes. It only records, checks, reminds, and helps you avoid context loss.

## 快速开始 / Quick Start

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

首次没有配置时，交互式 `./ctx ui` 会引导你选择语言和默认数据目录。非交互环境会继续使用默认目录，并提示可运行 `./ctx setup`。`./ctx ui` 会启动 `127.0.0.1` 本地页面，并尽量自动打开浏览器；如果自动打开失败，只会打印一行可手动访问的 URL。

On first interactive launch, `./ctx ui` asks for language and the default ledger directory. In non-interactive use, it keeps the built-in default and tells you to run `./ctx setup`. The UI binds only to `127.0.0.1` and prints the URL if the browser cannot be opened automatically.

网页默认是行动仪表板：顶部显示行动指标，主区域是可筛选的密集表格。新增项目只需要名称和下一步动作，状态默认 `todo`，优先级默认 `medium`。provider、surface、agent、repo 和 rules 在展开行的高级设置里维护，默认不会打扰日常使用。

备用 CLI：

```bash
./ctx now
./ctx next
./ctx list
./ctx doctor
```

要设置默认数据目录和语言：

```bash
./ctx setup
```

To override the ledger for one run:

```bash
./ctx --data-dir /path/to/ledger ui
CTX_LEDGER_DIR=/path/to/ledger ./ctx ui
```

## Developer Install

From this repository, you can run `ctx` without installing it globally:

```bash
uv run ctx --help
uv run ctx ui --no-open
uv run ctx --data-dir samples/ledger ui --no-open
uv run ctx --data-dir samples/ledger now
```

In this source checkout, use `uv run ctx ...`. Release package examples use `./ctx ...`.

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
scripts/ui_browser_smoke.sh
```

The HTTP smoke uses a temporary ledger and starts `uv run ctx ui --no-open --port 0`. It verifies the Chinese action dashboard homepage, creates a project through the HTTP form, quick-updates status/priority, checks advanced fields are preserved, and runs `uv run ctx now` plus `uv run ctx doctor`.

The browser smoke runs real headless Chromium through Playwright. First-time setup requires:

```bash
uv run --extra dev playwright install chromium
```

If Chromium launches with missing system libraries, run `uv run --extra dev playwright install-deps chromium` or install the named Ubuntu package reported by the smoke script.

It compares desktop, interaction, and mobile screenshots against `tests/ui_snapshots/`, checks for horizontal overflow and clipped controls, clicks the status/priority pill menus, and verifies the YAML ledger was updated without losing other fields. When the intended UI changes, update baselines with:

```bash
scripts/ui_browser_smoke.sh --update
```

## Release Checklist

Before tagging or publishing a release, run the same minimum checks used by CI:

```bash
scripts/release_check.sh
```

Do not release if this command fails. It runs the pytest suite, the local UI HTTP smoke check, and the real-browser visual smoke check. The pytest suite covers the store, CLI, schemas, doctor, and UI handler behavior; the smoke scripts cover the local HTTP path, the shared YAML ledger flow, the JSON quick-update path used by the inline menus, and the Chromium-rendered desktop/mobile layout.

## Data Directory

`ctx` reads two YAML files from a ledger directory. They remain the only business data source:

```text
projects.yml
providers.yml
```

Resolution order:

1. `--data-dir`
2. `CTX_LEDGER_DIR`
3. project config found by walking upward from the current directory: `.ctx/config.yml`
4. user config `~/.config/ctx/config.yml`
5. `~/.local/share/ctx/ledger`

User and project config files store only launch preferences:

```yaml
ledger_dir: /absolute/path/to/ledger
language: zh
```

`language` is saved as `zh` or `en`. `uv run ctx setup` from source, or `./ctx setup` from a release package, still accepts `auto`, but resolves it once and writes the detected language so later CLI/UI output does not drift between entry points. Relative paths entered through setup are saved as absolute paths. Changing the default ledger from the web settings panel affects the next launch; the current UI keeps using the ledger it started with.

中文说明：`projects.yml` 和 `providers.yml` 仍是唯一业务数据源。`~/.config/ctx/config.yml` 和 `.ctx/config.yml` 只保存默认 ledger 路径和语言偏好，不保存项目、provider、凭据或远程配置。项目级 `.ctx/config.yml` 是本机偏好，默认应忽略提交；本仓库提供 `.ctx/config.example.yml` 作为示例。

For daily use, point `ctx` at your private ledger directory:

```bash
uv run ctx setup
uv run ctx init
uv run ctx add my-project --status doing --next-action "Decide the next single action"
uv run ctx now
```

From a release package, replace `uv run ctx` with `./ctx`.

From this repository, an explicit ledger can be set with `CTX_LEDGER_DIR`:

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
uv run ctx setup
```

Initialize the ledger:

```bash
uv run ctx init
```

Start the local web UI:

```bash
uv run ctx ui --no-open
```

The web UI includes a compact action summary strip, search, status and priority menu filtering, alert-only filtering, a dense action table, row-level status/priority pill saves, minimal new-project creation, expanded editing, a settings menu, and an on-demand Doctor panel.

Add a project:

```bash
uv run ctx add local-ai-ctx --status doing --priority high --next-action "Write the next handoff note"
```

Check what to work on now:

```bash
uv run ctx now
uv run ctx next
```

Inspect projects:

```bash
uv run ctx list
uv run ctx show local-ai-ctx
```

Check ledger consistency:

```bash
uv run ctx doctor
```

Run the same commands without installing `ctx` by prefixing them with `uv run`:

```bash
uv run ctx doctor
uv run ctx --data-dir samples/ledger now
```

## Supported Commands

```bash
uv run ctx ui --no-open
uv run ctx setup
uv run ctx init
uv run ctx add <project-id> --next-action "<next action>"
uv run ctx now
uv run ctx list
uv run ctx show <project>
uv run ctx next
uv run ctx doctor
```

`ctx init` creates an empty ledger directory with `projects.yml` and `providers.yml`. It does not overwrite existing files.

`ctx setup` interactively saves the default ledger path and language to either `~/.config/ctx/config.yml` or the current project's `.ctx/config.yml`. If you move from one ledger to a new empty target, it can copy `projects.yml` and `providers.yml`; if the target already has a complete ledger, it adopts that directory without copying or overwriting.

`ctx ui` creates the ledger if needed and starts a local-only web UI on `127.0.0.1`. It keeps `projects.yml` and `providers.yml` as the source of truth. If started with `--data-dir` or `CTX_LEDGER_DIR`, web settings can still save a future default path, but the current run is not hot-switched.

`ctx add` creates a minimal project entry. It requires a project id and next action, and defaults to `todo` status and `medium` priority.

`ctx doctor` checks ledger consistency. It is read-only, exits non-zero for errors, and reports warnings without blocking.

This first MVP writes through `init`, `add`, and the local UI. It does not run Git checks, write handoffs, read secrets, or perform push, merge, rebase, or provider switching.

Keep personal ledger files outside this repository. The files in `samples/ledger` are synthetic examples for documentation and tests.

## 维护红线 / Maintenance Boundaries

`ctx` 是本地单用户行动仪表板，不是管理后台。`projects.yml` 和 `providers.yml` 仍是唯一数据源；CLI 和 `ctx ui` 都只读写这两个文件。

不要为这个 MVP 引入前端框架、构建链、数据库、登录、多用户、远程服务、provider switching、Git 操作、凭据处理、完整 YAML 编辑器或后台 daemon。

`ctx ui` 必须继续使用 Python 标准库 HTTP 服务和内嵌 HTML/CSS/少量原生 JS。允许的效率功能是指标卡、搜索、状态/优先级筛选、密集行动表格、展开编辑，以及 status/priority 快捷修改。

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
