# ctx 快速开始

`ctx` 是一个本地优先的 AI 工作台上下文管理工具。普通用户只需要运行本地网页，不需要先学习 YAML。

## 1. 下载

从 GitHub Release 下载 Linux/WSL 包，例如：

```bash
ctx-linux-x86_64.tar.gz
```

解压后进入目录：

```bash
tar -xzf ctx-linux-x86_64.tar.gz
cd ctx-linux-x86_64
```

## 2. 启动网页

```bash
./ctx ui
```

首次交互式启动会先询问语言和默认数据目录；非交互启动会使用内置默认目录：

```text
~/.local/share/ctx/ledger
```

然后启动本地页面并尽量自动打开浏览器。`--no-open` 或浏览器没有自动打开时，终端里会显示一行 `ctx UI：http://127.0.0.1:.../  ledger：...  Ctrl+C 停止`，复制地址到浏览器即可。

## 3. 日常使用

在网页里可以：

- 查看顶部紧凑行动指标
- 按搜索、状态菜单、优先级菜单和警示筛选密集表格
- 用“名称 + 下一步动作”快速新增项目
- 用行内 pill 菜单即时修改项目状态和优先级
- 更新下一步动作
- 展开项目行，在“高级设置”里维护 provider、surface、agent、repo 和 rules

数据会写回本机的 YAML 文件：

```text
projects.yml
providers.yml
```

这些文件仍然是唯一数据源，CLI 和网页看到的是同一份内容。

## 4. 常用备用命令

```bash
./ctx now
./ctx next
./ctx list
./ctx doctor
```

如果要把数据放到其他目录：

```bash
CTX_LEDGER_DIR=/path/to/ledger ./ctx ui
```
