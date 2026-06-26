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

`ctx` 会自动创建默认数据目录：

```text
~/.local/share/ctx/ledger
```

然后启动本地页面并尽量自动打开浏览器。如果浏览器没有自动打开，终端里会显示一个 `http://127.0.0.1:.../` 地址，复制到浏览器即可。

## 3. 日常使用

在网页里可以：

- 新增项目
- 修改项目状态
- 修改优先级
- 更新下一步动作
- 展开高级设置，维护 provider、surface、agent、repo 和 rules

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

