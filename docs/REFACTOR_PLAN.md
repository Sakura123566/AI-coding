# 后端改造企划书（第 1 轮评审后的 5 项修改）

范围严格限定为评审报告里的 **1 → 3 → 4 → 5 → 9**，其余一律不动。
目标：不动契约字段名、不动主流程结构、不引入新依赖，只把"会在联调当天炸"和"演示体验"的问题补掉。

| 编号 | 问题 | 优先级 | 预估 |
|---|---|---|---|
| 1 | 检索全线失败仍返回 HTTP 200 | P0 | 20 min |
| 3 | 500 兜底把异常原文回给前端 | P0 | 15 min |
| 4 | 无缓存，重复查同一主题重复烧 LLM | P1 | 30 min |
| 5 | 全程无 logging，排障靠猜 | P1 | 30 min |
| 9 | README 与代码漂移 | P2 | 15 min |

---

## 一、P0-1：检索失败返回 5xx

**现状**：`backend/schemas.py` 里 `ResearchError.http_status` 默认 `200`；
`backend/sources/__init__.py::_as_upstream_error` 构造异常时没有传状态码，
于是"论文源全挂"时前端收到 **HTTP 200 + `{"status":"error",...}`**。
前端若用 `if (!res.ok) throw` 这类常见写法，会当成成功往下解析，`papers` 变成 undefined → 白屏。

**改法**：
- `MCP_TIMEOUT` → HTTP **504**（上游超时）
- `MCP_ERROR` → HTTP **502**（上游不可用）
- `EMPTY_KEYWORD` / `INVALID_KEYWORD` / `INVALID_REQUEST` 维持 **400**（客户端问题，本来就是 400）
- `LLM` 相关不在此路径（报告失败是 `status=success` + `report=null`，不变）

**不动的东西**：响应体结构、`error_code` 取值、`status` 字段全部不变。
`status="error"` 仍然是唯一权威判据，HTTP 码只是让常规 HTTP 客户端不再误判。

**风险**：如果队员2 已经写了"非 2xx 就弹错误框"以外的逻辑需要同步。
处理：改完在 `docs/API_HANDOFF.md` 顶部加一段"错误判据"说明，并当面同步一次。

---

## 二、P0-3：500 兜底不泄露内部细节

**现状**：`main.py::_unexpected_handler` 返回 `f"服务内部错误：{type(exc).__name__}: {exc}"`。
异常文本里可能包含 MCP 端点 URL、请求头、甚至 `?token=` 片段。

**改法**：
- 响应固定为 `error_body("INTERNAL_ERROR", ERROR_CODES["INTERNAL_ERROR"])`，不带任何异常细节。
- 异常细节改用 `logging.exception(...)` 写服务端日志（配合第 5 项）。
- 顺带给响应加 `X-Request-ID` 头，日志里带上同一个 ID，前端报错时能凭 ID 回查日志。

**不动的东西**：`error_code=INTERNAL_ERROR` 与 HTTP 500 不变。

---

## 三、P1-4：加内存结果缓存

**现状**：同一个关键词点两次 = 两次检索 + 两次 LLM 调用，`LLM_TIMEOUT=90`，演示现场很容易转圈。

**改法**：新增 `backend/cache.py`，`pipeline.run_research` 外层包一层。

- 键：`(keyword, limit)`，忽略大小写与首尾空格。
- 只缓存**有论文且报告生成成功**的结果（`count>0` 且 `report` 非 null）。
  空结果、报错、报告降级（`report_error` 非空）一律不缓存，保证能重试。
- TTL 默认 600 秒，容量默认 64 条，超出按 LRU 淘汰。
- 用 `threading.Lock` 保证并发安全（FastAPI 是多线程跑同步接口的）。
- `CACHE_ENABLED=false` 可整体关闭；命中时写一条 log，不改响应体。

**不动的东西**：响应体一个字段都不加。缓存对用户是透明的。

---

## 四、P1-5：加 logging 体系

**现状**：全项目零 `logging`，只有 subprocess 的 stderr。

**改法**：新增 `backend/logging_setup.py`，`main.py` 启动时调用一次。

- 格式：`时间 级别 [request-id] logger - 消息`
- 级别由 `LOG_LEVEL` 控制，默认 `INFO`
- 记录点：
  - 请求开始/结束（关键词、limit、耗时、count、是否命中缓存）
  - 每个来源失败与降级（与 `warnings` 同步）
  - 报告生成失败原因
  - 未捕获异常（`logging.exception`，带堆栈）
- 只往 stderr 写，不落文件（部署交给队员3 决定重定向方式）

---

## 五、P2-9：修 README 与代码漂移

- 目录结构补 `sources/mcp_ws.py`、`llm/translate.py`、`docs/contract/success_real.json`
- "8 个场景"改为实际的 6 个场景
- 配置项表补 `CACHE_ENABLED / CACHE_TTL / CACHE_MAX_ENTRIES / LOG_LEVEL`
- `API_HANDOFF.md` 补错误判据说明（HTTP 码 + `status` 字段）

---

## 验证方式

1. `python scripts/smoke_test.py`（mock 源，离线）连跑 5 次，必须 5/5 全绿。
2. 断言新增行为：
   - 检索失败时 HTTP 码为 5xx 而不是 200
   - 500 兜底响应里不含异常类名
   - 第二次相同请求命中缓存（日志可见，且响应体与首次一致）
3. 跑完再读一遍改动文件做二次检查。

## 明确不做

换 MCP 官方 SDK、加 Redis / 数据库、异步化重构、加鉴权、加限流。
这些对"9-26 交付一个能演示的 Demo"是负收益，放进产品化差距清单里另行评估。
