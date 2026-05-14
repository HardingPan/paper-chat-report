---
name: paper-chat-report
version: 2.1.0
description: Use when the user wants to turn a role-labeled paper-reading dialogue markdown export into a high-quality Chinese paper report, with the dialogue treated as explanation material and the original paper treated as the fact-correction source.
---

# Paper Chat Report

这个 skill 处理的是一种很具体但很常见的工作流：

- 你已经和某个 AI 围绕一篇论文聊过
- 现在手里有一份 role-labeled 的 markdown 对话导出
- 你希望把这份对话整理成一份可归档、可继续编辑、可单独阅读的中文论文报告

它的目标不是“清洗聊天记录”，而是：

- 把对话里已经讲清楚的内容提炼出来
- 用原论文做事实纠偏和缺口补全
- 最终重写成一份独立的 markdown 报告

## 适用边界

优先用于这些场景：

- 输入主材料是一个 role-labeled markdown 对话导出
- 对话内容已经包含较多方法解释、公式说明、实验讲解
- 希望结果接近个人论文笔记，而不是 transcript
- 希望报告以中文为主，英文术语保留

不适合这些场景：

- 没有对话导出，只有 PDF 或论文链接
- 主要输入不是 role-labeled 对话，而是原论文本身
- 想做交互式共读
- 想保留问答式原貌
- 想生成 reviewer 风格评审意见

## 主要输出

默认输出到当前仓库：

- 最终报告：`docs/papers/<slug>.md`
- 工作目录：`.tmp/analysis/paper-chat-report/<slug>/`

工作目录至少包含：

- `manifest.json`
- `source.json`
- `dialogue-source.md`
- `dialogue-normalized.json`
- `dialogue-cleaned.md`
- `dialogue-section-map.json`
- `teaching-map.md`
- `equation-cards.json`
- `report-context.md`

如果成功拿到原论文，还会生成：

- `paper.txt`
- `paper.struct.md`
  - 仅当 `docling` 可用且成功时生成
- `paper.pdf`
  - 仅当需要从远程下载 PDF 时生成

## 支持输入

当前版本支持：

- 一个 role-labeled markdown 对话导出
- 可选的原论文来源：
  - 本地 PDF
  - arXiv `abs` 链接
  - arXiv `pdf` 链接
  - 直接 PDF URL

如果没有显式提供原论文来源，默认按这个顺序补：

1. 从对话里找 `.pdf` 文件名或路径
2. 尝试在对话文件同目录定位同名 PDF
3. 从对话里提取论文标题
4. 用标题做有限的远程检索，优先找可直接下载的原文 PDF

如果仍然拿不到原文，不要假装补全成功。保留中间产物并明确说明“对话可整理，但原文未稳定解析”。

## 工作流

下面命令中的 `<skill-dir>` 指安装后的 `paper-chat-report` skill 根目录，例如：

- `~/.codex/skills/paper-chat-report`
- `~/.claude/skills/paper-chat-report`
- `~/.agents/skills/paper-chat-report`

如果只是让 AI 读取本 skill 自带脚本或参考文件，直接按相对路径 `scripts/...`、`references/...` 相对 skill 根目录解析即可。

1. 初始化产物路径。

```bash
python3 <skill-dir>/scripts/init_paper_chat_report_artifacts.py \
  --root . \
  --dialogue "/absolute/path/to/export.md" \
  --json
```

如果用户已经给了原论文来源，可以一起传入：

```bash
python3 <skill-dir>/scripts/init_paper_chat_report_artifacts.py \
  --root . \
  --dialogue "/absolute/path/to/export.md" \
  --source "/absolute/path/to/paper.pdf" \
  --json
```

2. 提取对话骨架、补原论文、生成上下文。

```bash
python3 <skill-dir>/scripts/extract_paper_chat_bundle.py \
  --dialogue "/absolute/path/to/export.md" \
  --out-dir ".tmp/analysis/paper-chat-report/<slug>" \
  --json
```

如果用户已经给了论文来源，也传进去：

```bash
python3 <skill-dir>/scripts/extract_paper_chat_bundle.py \
  --dialogue "/absolute/path/to/export.md" \
  --source "/absolute/path/to/paper.pdf" \
  --out-dir ".tmp/analysis/paper-chat-report/<slug>" \
  --json
```

3. 默认优先读取这些中间产物，而不是直接把全文 transcript 塞进上下文：

- `manifest.json`
- `source.json`
- `dialogue-section-map.json`
- `teaching-map.md`
- `equation-cards.json`
- `report-context.md`
- `paper.struct.md`（如果存在）
- `paper.txt`（如果存在）

4. 按 `report-context.md` 和 `references/report-contract.md` 写最终报告。

5. 如果当前报告来自旧版 `paper-chat-report`，或出现章节编号漂移，先做一次结构规范化：

```bash
python3 <skill-dir>/scripts/normalize_paper_chat_report.py \
  --report "docs/papers/<slug>.md" \
  --in-place \
  --json
```

6. 再做校验：

```bash
python3 <skill-dir>/scripts/validate_paper_chat_report.py \
  --report "docs/papers/<slug>.md" \
  --require-pass
```

## 写作规则

- 报告必须是 standalone 文档，而不是 transcript
- 中文为主，英文术语、方法名、模块名、变量名保留
- 对话是解释材料来源，论文原文是事实纠偏来源
- 如果对话与论文冲突，以论文为准
- 方法部分默认按”问题拆解 -> 阶段协作 -> 关键约束 -> 执行顺序”来组织
- 公式必须嵌进方法解释，而不是单独堆一节公式抄录
- 可以吸收对话里的好解释，但不要保留 `You said`、`ChatGPT said`、`继续` 之类聊天痕迹
- 实验部分只抓最能支撑主张的证据，不做流水账
- 自己阅读源对话文件，识别并整合用户追问环节的洞见

## 默认报告结构

1. 标题 + 三句话总结
2. 阅读入口
3. 基本信息（可选：符号说明）
4. 研究问题与核心困难
   - 4.1 问题背景
   - 4.2 研究现状与局限（相关工作整合于此）
   - 4.3 核心研究问题
5. 核心贡献
6. 整体主线
7. 方法总览与系统分解
8. 方法详解（公式嵌入各小节，不单独汇总）
9. 图表与实验解读（用 `[[FIG:n|desc]]` 标记插图位置）
10. 局限与边界
11. 结论
12. 参考链接

**结构调整说明**：
- 相关工作并入第 4.2 节，从"问题驱动"视角展开
- 删除独立的"关键机制与公式速查"章节，公式在首次出现时完整定义
- 删除"建议插图"章节，改用语义标记 `[[FIG:n|描述]]` 在正文标注

## 图片标注语法

在正文的合适位置插入图片引用标记：

```markdown
[[FIG:4|学习曲线对比：SimDist vs baselines，突出15-30分钟数据点的性能]]

[[TAB:2|消融实验结果]]
```

- `FIG:n` = 论文第 n 个图
- `TAB:n` = 论文第 n 个表
- `|` 后是对图表内容的简短描述

## 增强格式输出（可选）

对于语雀、Notion 等第三方 Markdown 笔记软件，提供增强格式处理：

```bash
python3 <skill-dir>/scripts/enhance_report_format.py \
  --input "docs/papers/<slug>.md" \
  --output "docs/papers/<slug>-enhanced.md" \
  --platform yuque
```

支持的平台：
- `standard`：标准 Markdown + LaTeX（默认）
- `yuque`：语雀格式（双栏卡片、折叠块、颜色标记）
- `notion`：Notion 格式（优化导入兼容性）
- `obsidian`：Obsidian 格式（Callouts、Mermaid）

### 增强功能

**1. ASCII 公式自动转 LaTeX**

自动识别并转换：
```
z_t = E_θ(o_t)          →  $$z_t = E_\theta(o_t)$$
h_t = C_θ(...)          →  $$h_t = C_\theta(...)$$
L_{pretrain} = ...      →  $$\mathcal{L}_{\text{pretrain}} = ...$$
Σ_{i=0}^{T} ...         →  $$\sum_{i=0}^{T} ...$$
```

**2. 双栏对比布局**

语雀输出：
```markdown
:::row{gutter="16"}
:::col{span="12"}
**传统 RL 微调**
- 同时学习 reward, value, dynamics
:::
:::col{span="12"}
**SimDist 适配**
- 仅学习 dynamics
:::
:::
```

**3. 折叠块（Details）**

长公式推导、消融实验详情自动收拢：
```markdown
:::toggle{title="展开：梯度推导"}
推导内容...
:::
```

**4. 语义图片标记转换**

把 `[[FIG:n|描述]]` 和 `[[TAB:n|描述]]` 转为平台特定格式：

| 平台 | 渲染效果 |
|------|----------|
| `yuque` | `<span style="color:#ff6b6b">**[插入图4：描述]**</span>` |
| `notion` | `<span style="color:#ff6b6b">**[插入图4：描述]**</span>` |
| `standard` | `🔴 **[插入图4：描述]**` |

**5. 颜色标记**

关键状态高亮：
```markdown
<span style="color:#1677ff">**冻结**</span>
<span style="color:#52c41a">**微调**</span>
```

默认只要求 `requirements.txt` 里的核心依赖。

如果需要 `docling` 的结构化 PDF 增强，再额外安装 `requirements-optional.txt`。

参考文档：`references/platform-formats.md`

## Guardrails

- 不要把对话导出当成最终报告直接轻微改写
- 不要保留 role marker、回合编号、继续提示语
- 不要把对话中的错误解释原样写入最终稿
- 不要在原论文来源未解决时假装做了公式核对
- 不要把 methods 写成关键词堆砌
- 如果 `equation-cards.json` 存在，优先用它把公式重新嵌回方法叙述
- 如果 `report-context.md` 存在，优先从它进入成稿，不要重新从零整理 transcript
