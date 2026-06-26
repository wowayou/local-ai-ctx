from __future__ import annotations


STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "app_help": "本地优先的 AI 工作上下文管理器。",
        "data_dir_help": "包含 projects.yml 和 providers.yml 的 ledger 目录。",
        "error": "错误",
        "initialized": "已初始化 ctx ledger：{path}",
        "already_initialized": "ctx ledger 已存在：{path}",
        "created": "已创建 {name}",
        "exists": "已存在 {name}",
        "added_project": "已添加项目 {project_id} 到 {path}",
        "setup_saved": "已保存设置：{path}",
        "setup_copied": "已复制现有 ledger 文件到 {path}",
        "setup_adopted_existing": "目标目录已有完整 ledger，已采用：{path}（未复制、未覆盖）",
        "setup_non_interactive": "ctx setup 需要交互式终端。非交互环境可使用 --data-dir 或 CTX_LEDGER_DIR。",
        "setup_language": "语言 language (auto/zh/en，auto 会保存为当前检测结果)",
        "setup_dir_choice": "数据目录：1=默认用户目录，2=当前目录 data/ledger，3=自定义路径",
        "setup_custom_dir": "自定义 ledger 路径",
        "setup_config_scope": "设置保存位置：1=用户级 ~/.config/ctx/config.yml，2=当前项目级 .ctx/config.yml",
        "setup_invalid_dir_choice": "数据目录选项必须是 1、2 或 3",
        "setup_invalid_scope_choice": "设置保存位置必须是 1 或 2",
        "setup_copy": "是否复制当前 ledger 的 projects.yml/providers.yml 到新目录？",
        "ui_first_run": "首次启动需要选择默认数据目录。之后可用 ctx setup 修改。",
        "ui_skip_setup": "未检测到用户配置；非交互启动将使用默认目录。可运行 ctx setup 设置默认 ledger。",
        "ui_started": "ctx UI：{url}  ledger：{path}  Ctrl+C 停止",
        "ui_running": "ctx UI 正在运行：{url}",
        "ui_ledger": "ledger：{path}",
        "ui_stop": "按 Ctrl+C 停止。",
        "ui_stopped": "ctx UI 已停止。",
        "ui_open_failed": "浏览器未自动打开，请手动访问：{url}",
    },
    "en": {
        "app_help": "Local AI workbench context manager.",
        "data_dir_help": "Ledger directory containing projects.yml and providers.yml.",
        "error": "Error",
        "initialized": "Initialized ctx ledger at {path}",
        "already_initialized": "ctx ledger already initialized at {path}",
        "created": "created {name}",
        "exists": "exists {name}",
        "added_project": "Added project {project_id} to {path}",
        "setup_saved": "Saved ctx settings at {path}",
        "setup_copied": "Copied existing ledger files to {path}",
        "setup_adopted_existing": "Target already has a complete ledger; using {path} without copying or overwriting.",
        "setup_non_interactive": "ctx setup requires an interactive terminal. In non-interactive use, pass --data-dir or CTX_LEDGER_DIR.",
        "setup_language": "Language (auto/zh/en; auto is saved as the detected language)",
        "setup_dir_choice": "Ledger directory: 1=default user directory, 2=current directory data/ledger, 3=custom path",
        "setup_custom_dir": "Custom ledger path",
        "setup_config_scope": "Save settings to: 1=user ~/.config/ctx/config.yml, 2=current project .ctx/config.yml",
        "setup_invalid_dir_choice": "Directory choice must be 1, 2, or 3",
        "setup_invalid_scope_choice": "Settings location must be 1 or 2",
        "setup_copy": "Copy projects.yml/providers.yml from the current ledger to the new directory?",
        "ui_first_run": "First launch needs a default ledger directory. You can change it later with ctx setup.",
        "ui_skip_setup": "No user config found; non-interactive launch will use the default directory. Run ctx setup to choose a default ledger.",
        "ui_started": "ctx UI: {url}  ledger: {path}  Ctrl+C to stop",
        "ui_running": "ctx UI running at {url}",
        "ui_ledger": "ledger: {path}",
        "ui_stop": "Press Ctrl+C to stop.",
        "ui_stopped": "ctx UI stopped.",
        "ui_open_failed": "Browser did not open automatically. Open this URL manually: {url}",
    },
}


def t(lang: str, key: str, **values: object) -> str:
    table = STRINGS.get(lang, STRINGS["en"])
    template = table.get(key, STRINGS["en"].get(key, key))
    return template.format(**values)
