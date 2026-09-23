# 情绪触发规则

> 日期：2026-07-15
> 阶段：Phase 5.4 Intelligent Emotion Engine

## 优先级

Emotion Engine 现在按以下优先级选择 Avatar：

```text
任务结果 > 工具/工作流 > 服务端显式 emotion > 用户语境/persona
```

这保证搜索论文、阅读论文、调用 Codex 等 workflow 状态不会被普通 `happy`、`explaining` 等 persona 状态抢走。

## Workflow 状态

| 状态 | 主 GIF | 典型触发 |
| --- | --- | --- |
| `论文搜索` | `workflow_searching.gif` | `search_paper`, `search_arxiv`, `search_semantic_scholar`, `web_search` |
| `阅读论文` | `workflow_reading.gif` | `paper_summary`, `paper_analyze`, `paper_compare`, `read_paper` |
| `编写代码` | `workflow_coding.gif` | `codex`, `codex_tool`, `code_tool`, `generate_code`, `modify_code` |
| `协作` | `workflow_collaborating.gif`，缺失时回退 `workflow_coding.gif` | `tool_call`, `mcp_tool`, `multi_agent` |
| `灵光一现` | `workflow_eureka.gif` | `success`, `done`, `task_success`, `bug_resolved`, `key_paper_found` |

`灵光一现` 是临时状态，默认持续 3 秒，随后恢复到 `细心讲解`。

## Persona 状态

| 状态 | 主 GIF | 典型触发 |
| --- | --- | --- |
| `开心` | `persona_happy.gif` | 用户夸奖、感谢、积极反馈 |
| `温柔安抚` | `persona_comforting.gif` | 用户焦虑、失败、网络错误、压力表达 |
| `细心讲解` | `persona_explain.gif` | 概念解释、天气、日程、翻译、新闻、故事 |
| `细心讲解2` | `persona_deep_explain.gif` | 深度阅读、需求提取、论文对比 |
| `严肃讲解` | `persona_serious_explain.gif` | Bug 分析、风险评估、方案审查 |
| `严肃指正` | `persona_correction.gif` | 配置错误、路径错误、依赖缺失、明确纠错 |
| `待机` | `persona_idle.gif` | 空闲、设备回到 idle |
| `待机疲惫` | `persona_idle_tired.gif` | 60 秒无交互 |

## 基础功能映射

| 功能 | Avatar |
| --- | --- |
| 天气 | `细心讲解` |
| 日程 | `细心讲解` |
| 闹钟 | `温柔安抚` |
| 音乐 | `开心` |
| 故事 | `细心讲解` |
| 翻译 | `细心讲解` |
| 新闻 | `细心讲解` |

## 兼容规则

- 旧 emotion 名称仍可用，例如 `happy` -> `开心`，`sad` -> `温柔安抚`，`surprised` -> `论文搜索`。
- 旧资源文件名也已被新 GIF 覆盖，例如 `searching.gif` 来自 `论文搜索.gif`，`success.gif` 来自 `灵光一现.gif`。
