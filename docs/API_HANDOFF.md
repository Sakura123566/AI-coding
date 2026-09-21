# 前后端交接说明（队员1 → 队员2 / 队员3）

> 字段已冻结。任何人要改字段名，必须在群里说一声，改完同步更新本文件和 `docs/contract/*.json`。

## 1. 接口路径与方法

| 用途 | 方法 | 路径 |
|---|---|---|
| 健康检查 | GET | `/api/health` |
| 主接口 | POST | `/api/research/run` |

后端默认地址：`http://127.0.0.1:8000`
Swagger 自测页：`http://127.0.0.1:8000/docs`

## 2. 请求字段

```json
{ "keyword": "Graph Neural Networks", "limit": 10 }
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| keyword | string | 是 | — | 研究主题，中英文均可；空白会返回 `EMPTY_KEYWORD` |
| limit | int | 否 | 10 | 1–30，超出范围返回 `INVALID_REQUEST` |

## 3. 成功响应

完整样例见 `docs/contract/success.json`（另有真实数据样例 `success_arxiv.json`）。

```json
{
  "status": "success",
  "keyword": "Graph Neural Networks",
  "resolved_keyword": null,
  "count": 10,
  "papers": [
    {"id":"P1","title":"...","authors":["..."],"year":2025,
     "abstract":"...","url":"https://...","source":"arXiv"}
  ],
  "report": {
    "overview": "...",
    "themes": [{"name":"...","description":"...","paper_ids":["P1"]}],
    "research_trends": ["..."],
    "reading_path": [{"step":1,"paper_ids":["P1"],"reason":"..."}],
    "exploration_questions": ["..."],
    "limitations": "..."
  },
  "report_error": null,
  "warnings": [],
  "message": null
}
```

**可能为空的字段（前端必须做兜底文案）：**

| 字段 | 为空时的表现 | 建议文案 |
|---|---|---|
| `papers[].authors` | `[]` | 不显示作者行 |
| `papers[].year` | `null` | "年份未知" |
| `papers[].abstract` | `null` | "暂无摘要"，折叠按钮禁用 |
| `papers[].url` | `null` | 标题不可点击 |
| `papers[].source` | `null` | 不显示来源标签 |
| `report.reading_path[].reason` | `""` | 省略原因行 |
| 整个 `report` | `null` | 看 `report_error` |

**新增可选字段 `resolved_keyword`**（2026-09-21 加，前端可忽略）：
用户输入中文主题时，后端会先转成英文再去检索（arXiv 不吃中文查询），
`keyword` 仍是用户原样输入，`resolved_keyword` 是实际检索用的英文词；
英文输入时为 `null`。同时 `warnings` 里会有一条"中文主题已转为英文检索：X → Y"。
建议在论文列表上方显示一行小字：`已按 “{resolved_keyword}” 检索`。

## 4. 失败响应（HTTP 状态码 + body 都是契约结构）

```json
{ "status": "error", "error_code": "MCP_TIMEOUT", "message": "论文检索服务暂时不可用…" }
```

| error_code | HTTP | 前端该做什么 |
|---|---|---|
| `EMPTY_KEYWORD` | 400 | 输入框提示 "请输入研究主题" |
| `INVALID_KEYWORD` | 400 | 提示主题过长 |
| `INVALID_REQUEST` | 400 | 提示参数错误 |
| `MCP_TIMEOUT` | 200 | "检索服务超时，请重试" + 重试按钮 |
| `MCP_ERROR` | 200 | "检索服务暂不可用，请重试" + 重试按钮 |
| `LLM_ERROR` | 200 | 论文照常展示，报告区提示 `report_error` |
| `INTERNAL_ERROR` | 500 | "服务内部错误，请重试" |

> 注意：上游失败用 **HTTP 200 + body 里 status=error**。前端请**先判断 `body.status`，再看 HTTP 状态码**，否则 axios 会把 200 当成成功。

## 5. 三种"看起来像失败但其实不是"的情况

1. **无结果**：`status=success`、`count=0`、`papers=[]`、`report=null`、`message="没有找到论文…"` → 走"无结果"状态页。
2. **报告降级**：`status=success`、有 `papers`、但 `report=null` 且 `report_error` 有值 → 论文照常展示，报告区显示 `report_error`。
3. **本地样例模式**：`warnings` 里带 "本地样例报告（LLM_PROVIDER=mock）" → 说明后端还没接真模型，演示前必须切回真实模型。

## 6. 跨域（CORS）

后端已开启 CORS，允许来源由 `.env` 的 `CORS_ORIGINS` 控制，默认 `*`。前端开发期两种做法：

- 直接请求 `http://127.0.0.1:8000/api/...`（推荐，后端已放开跨域）；
- 或在 Vite 里配代理：`server.proxy['/api'] = { target: 'http://127.0.0.1:8000', changeOrigin: true }`。

## 7. 前端必做的状态机

```
初始 → 检索中(禁用按钮) → 分析中("已找到论文，正在生成研究导航…") → 成功
                                   └→ 无结果 / 失败(保留输入内容 + 重试)
```

前端无法区分"检索中"和"分析中"（后端一次返回），建议：**发起请求即显示"正在检索论文…"，2.5 秒后自动切成"已找到论文，正在生成研究导航…"**，拿到响应再切终态。

## 8. 联调顺序（照企划案第4部分）

1. 队员1 让 `/api/health` 返回 ok ✅（已完成）
2. 队员1 用 mock 数据让 `/api/research/run` 返回成功 JSON ✅（已完成，`docs/contract/success_mock.json`）
3. 队员2 接这份 JSON，确认每个字段显示正确
4. 队员3 查字段缺失 / 错误响应 / 空结果
5. 队员1 把 mock 换成真实检索 + 真实模型
6. 字段冻结，全员同一主题跑完整流程
