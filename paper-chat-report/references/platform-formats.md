# Platform-Specific Output Formats

This document defines how `paper-chat-report` generates enhanced output for different platforms.

## Supported Platforms

| Platform | Key Features | Syntax Family |
|----------|--------------|---------------|
| `standard` | Pure Markdown, LaTeX math | GitHub Flavored Markdown |
| `yuque` | 双栏卡片、折叠块、颜色标记 | Yuque Extended Markdown |
| `notion` | Column blocks, toggles, callouts | Notion-flavored Markdown |
| `obsidian` | Callouts, Mermaid, Dataview | Obsidian Extended |

## Feature Mapping

### 1. Collapsible Content

```markdown
<!-- standard: HTML details -->
<details>
<summary>展开：标题</summary>
内容
</details>

<!-- yuque: 折叠块语法 -->
:::toggle{title="标题"}
内容
:::

<!-- notion: Toggle list (import as toggle) -->
> **标题**
> 内容
```

### 2. Multi-Column Layout

```markdown
<!-- standard: HTML table simulation -->
<table>
<tr>
<td width="50%">

**左栏标题**
- 内容

</td>
<td width="50%">

**右栏标题**
- 内容

</td>
</tr>
</table>

<!-- yuque: 双栏卡片 -->
:::row{gutter="16"}
:::col{span="12"}
**左栏标题**
- 内容
:::
:::col{span="12"}
**右栏标题**
- 内容
:::
:::

<!-- notion: Column list (limited support via import) -->
<!-- Use HTML table or consecutive blocks -->
```

### 3. Color Highlighting

```markdown
<!-- standard: bold + emoji prefix -->
**🟦 冻结** | **🟩 微调**

<!-- yuque: HTML span with color -->
<span style="color:#1677ff">**冻结**</span>
<span style="color:#52c41a">**微调**</span>

<!-- notion: Background color (limited) -->
**`冻结`** <!-- with background color via import -->
```

### 4. Formula Display

```markdown
<!-- standard: LaTeX -->
$$z_t = E_\theta(o_t)$$

<!-- yuque: 支持 LaTeX，但需要 $ 包裹 -->
$z_t = E_\theta(o_t)$

<!-- notion: 支持 LaTeX blocks -->
$$z_t = E_\theta(o_t)$$
```

## ASCII Formula Detection Patterns

Common patterns to convert:

```
# Pattern 1: Simple assignment
z_t = E_θ(o_t)
→ $$z_t = E_\theta(o_t)$$

# Pattern 2: Function notation with subscripts
h_t = C_θ(o_{t-H:t-1}, a_{t-H:t-1})
→ $$h_t = C_\theta(o_{t-H:t-1}, a_{t-H:t-1})$$

# Pattern 3: Loss functions
L_{pretrain} = λ_1 L_{dynamics} + ...
→ $$\mathcal{L}_{\text{pretrain}} = \lambda_1 \mathcal{L}_{\text{dynamics}} + \dots$$

# Pattern 4: Summations
Σ_{i=0}^{T} ||ẑ_{t+i+1} - ...||_2
→ $$\sum_{i=0}^{T} \|\hat{z}_{t+i+1} - \dots\|_2$$

# Pattern 5: Hats and special chars
ẑ_{t+1:t+T}
→ $$\hat{z}_{t+1:t+T}$$
```

## Implementation Strategy

1. **Detection Phase**: Regex patterns to identify ASCII formulas
2. **Conversion Phase**: Transform to proper LaTeX
3. **Formatting Phase**: Apply platform-specific wrappers
4. **Output Phase**: Generate final markdown
