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

## 交给 AI 配置

如果你希望把安装和配置直接交给 AI，可以把下面这段话直接发给 Codex / Claude：

```text
帮我安装这个 skill：git@github.com:HardingPan/paper-chat-report.git

要求：
1. 如果当前环境已经有 Codex 的 skill-installer，优先直接从 GitHub 安装 `paper-chat-report/` 这个 skill path。
2. 如果没有可用的 skill-installer，就 clone 仓库后执行 `python3 install.py --upgrade`。
3. 如果我主要在 Codex 里使用，就优先安装到 `~/.codex/skills`。
4. 安装完成后，告诉我实际安装路径，并提醒我重启 Codex / Claude。
5. 如果缺依赖，就一并安装核心依赖；`docling` 先不用装，除非我后面明确要求。
```

如果你希望 AI 只装到 Codex，也可以直接发这段：

```text
把 `git@github.com:HardingPan/paper-chat-report.git` 里的 `paper-chat-report` skill 安装到我的 Codex。
优先用 skill-installer；不行就 clone 仓库并执行 `python3 install.py --target codex --upgrade`。
装完告诉我安装路径，并提醒我重启 Codex。
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

## 交给 AI 使用

安装完成后，如果你希望 AI 直接用这个 skill 处理论文对话导出，可以把下面这段话直接发给它：

```text
用 `paper-chat-report` 处理这份 role-labeled markdown 对话导出：`/absolute/path/to/export.md`

要求：
1. 先初始化 `docs/papers/` 和 `.tmp/analysis/paper-chat-report/` 下的中间产物。
2. 如果对话同目录下有对应 PDF，优先使用；否则按标题自动解析论文来源。
3. 优先读取 `report-context.md`、`teaching-map.md`、`equation-cards.json`、`paper.txt` / `paper.struct.md` 来组织成稿。
4. 最终输出一份独立的中文论文报告到 `docs/papers/<slug>.md`，不要保留 transcript 痕迹。
5. 完成后运行校验；如果需要，顺手再生成一个 `-enhanced.md` 的语雀版本。
```

如果你已经有原论文 PDF，也可以直接发更明确的版本：

```text
用 `paper-chat-report` 处理这份对话导出：`/absolute/path/to/export.md`
原论文 PDF 在：`/absolute/path/to/paper.pdf`

请你：
1. 先跑中间产物抽取。
2. 再按 `report-context.md` 和 `references/report-contract.md` 写最终报告。
3. 输出到 `docs/papers/<slug>.md`。
4. 最后运行校验，确保结构通过。
```

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
