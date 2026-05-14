# paper-chat-report

把 role-labeled 的论文阅读对话导出，整理成一份可单独阅读、可继续编辑的中文论文报告。

这个仓库包含两部分：

- `paper-chat-report/`：真正可安装的 skill 目录
- `install.py` / `install.sh`：新设备安装脚本，负责复制 skill 并安装核心依赖

## 快速安装

```bash
git clone git@github.com:HardingPan/paper-chat-report.git
cd paper-chat-report
python3 install.py --upgrade
```

如果你已经有 Codex 的 `skill-installer`，也可以直接从 GitHub 安装这个 skill：

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo HardingPan/paper-chat-report \
  --path paper-chat-report
```

安装脚本默认行为：

- 自动探测 `~/.codex/skills`、`~/.claude/skills`、`~/.agents/skills`
- 探测到哪个就装到哪个；如果一个都没有，默认装到 `~/.codex/skills`
- 自动安装核心依赖 `PyMuPDF`
- 复制后做一次脚本冒烟检查

安装完成后，重启 Codex / Claude 让新 skill 生效。

## 可选增强

如果你还想启用 `docling` 的结构化 PDF 解析增强：

```bash
python3 install.py --with-docling --upgrade
```

这会额外安装：

- `paper-chat-report/requirements-optional.txt`

如果你明确不想装 pip 依赖，也可以：

```bash
python3 install.py --skip-pip --upgrade
```

## 常用安装方式

只装到 Codex：

```bash
python3 install.py --target codex --upgrade
```

装到自定义 skills 目录：

```bash
python3 install.py --dest /path/to/skills --upgrade
```

## 手动运行脚本

安装后可先设一个变量：

```bash
SKILL_DIR=~/.codex/skills/paper-chat-report
```

初始化产物：

```bash
python3 "$SKILL_DIR/scripts/init_paper_chat_report_artifacts.py" \
  --root . \
  --dialogue "/absolute/path/to/export.md" \
  --json
```

抽取对话骨架和论文上下文：

```bash
python3 "$SKILL_DIR/scripts/extract_paper_chat_bundle.py" \
  --dialogue "/absolute/path/to/export.md" \
  --out-dir ".tmp/analysis/paper-chat-report/<slug>" \
  --json
```

校验最终报告：

```bash
python3 "$SKILL_DIR/scripts/validate_paper_chat_report.py" \
  --report "docs/papers/<slug>.md" \
  --require-pass
```

增强输出格式：

```bash
python3 "$SKILL_DIR/scripts/enhance_report_format.py" \
  --input "docs/papers/<slug>.md" \
  --output "docs/papers/<slug>-enhanced.md" \
  --platform yuque
```

## 目录结构

```text
paper-chat-report/
├── SKILL.md
├── agents/openai.yaml
├── references/
├── scripts/
├── requirements.txt
└── requirements-optional.txt
```
