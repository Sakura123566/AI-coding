# 前端对接文档 · 对话 / 登录 / 记忆 / 画像（给队员2）

版本：v1.0 ｜ 日期：2026-09-22 ｜ 提供方：队员1（后端）
状态：**接口已实现、已在真实 HTTP 上跑通 49 项验证**（含"重启服务后数据还在"）。

后端地址：`http://127.0.0.1:8000`（同一台机器时直接填这个；CORS 已放行 `*`）。
所有响应统一结构：成功 `{"status":"success", ...}`，失败 `{"status":"error","error_code":"...","message":"..."}`。

---

## 零、三件事先记住

1. **除登录注册外，所有请求都要带头**：`Authorization: Bearer <token>`。token 从注册/登录返回里拿，存 localStorage 即可。
2. **401 = 该去登录页了**；**503 = 上游挂了，提示重试**（不要自动连点重试）。
3. **`degraded: true` 时界面上要显示降级提示条**，别把降级回复当成正常 AI 回答展示。

---

## 一、注册登录 `/api/auth`

| 方法 | 路径 | 请求体 | 成功响应 |
|---|---|---|---|
| POST | `/api/auth/register` | `{username, password, display_name?}` | `{status, user_id, token, expires_in, token_type, user}` |
| POST | `/api/auth/login` | `{username, password}` | 同上 |
| GET | `/api/auth/me` | —（带头） | `{status, user, token_ttl}` |
| POST | `/api/auth/logout` | —（带头） | `{status, user_id, logged_out}` |

- username 2–32 字符，password ≥6 位（后端常量 `MIN_PASSWORD_LEN`，默认 6）。
- token 默认 7 天有效，过期返回 `TOKEN_EXPIRED`（401）。
- 响应里的 `user` 只有 `{id, username, display_name, avatar_id, created_at, last_login_at}`，**永远不含密码相关信息**。

---

## 二、会话与对话 `/api/chat`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat/sessions` | 新建会话，body 可空或 `{title?}` → `{session}` |
| GET | `/api/chat/sessions?limit=20&offset=0` | 会话列表，按最近更新排序 |
| GET | `/api/chat/sessions/{sid}/messages?limit=200` | 历史消息（正序，含 emotion，可直接回放） |
| POST | `/api/chat/message` | **主接口**，见下 |
| POST | `/api/chat/sessions/{sid}/close` | 关闭会话，同步整理长期记忆 + 刷新画像 |
| DELETE | `/api/chat/sessions/{sid}` | 删会话（级联删消息） |

### `POST /api/chat/message`

> v0.3.0：科研意图会同时返回 `report`、`report_error`、`resolved_keyword`、`warnings`；这些内容也会写入助手消息的 `payload`，刷新历史后可直接恢复。

请求：`{"session_id": "s-9f2c...", "content": "帮我查一下图神经网络的最新论文"}`

响应：

```json
{
  "status": "success",
  "message_id": 42,
  "user_message_id": 41,
  "reply": "我查到 8 篇……",
  "emotion": "excited",
  "intent": "research",
  "intent_mode": "rule",
  "mode": "live",
  "papers": [
    {"id": "P1", "title": "...", "title_zh": "中文标题", "authors": ["..."], "year": 2024, "abstract": "英文原文", "abstract_zh": "中文翻译", "abstract_summary_zh": "中文短摘要", "translation_status": "translated", "url": "...", "source": "openalex"}
  ],
  "report": {
    "overview": "...",
    "themes": [{"name": "...", "description": "...", "paper_ids": ["P1"]}],
    "research_trends": ["..."],
    "reading_path": [{"step": 1, "paper_ids": ["P1"], "reason": "..."}],
    "exploration_questions": ["..."],
    "limitations": "..."
  },
  "report_error": null,
  "resolved_keyword": "graph neural networks",
  "warnings": [],
  "recalled_memories": ["用户在研究图神经网络在推荐系统上的应用"],
  "used_keywords": ["graph neural network", "recommender system"],
  "degraded": false,
  "degrade_reason": null,
  "profile_used": true,
  "skills_used": ["实验设计检查"],
  "voice": {
    "enabled": true,
    "auto_play": true,
    "name": "Microsoft Xiaoxiao",
    "rate": 1.0,
    "pitch": 1.0
  }
}
```

字段说明：

| 字段 | 你要拿它做什么 |
|---|---|
| `reply` | 气泡正文 |
| `emotion` | **驱动 Q 版形象动作**，见下节 |
| `intent` | `research` 时可显示"已检索 N 篇论文"角标 |
| `mode` | `live`=真实模型；`mock`=本地样例（**此时界面要标注"样例模式"**） |
| `papers` | 有值时展示论文卡片，点 url 跳原文；`id` 是引用编号，与正文里的 `[P1]` 对应 |
| `report` | 科研意图时返回与 `/api/research/run` 相同的结构化导航报告 |
| `report_error` | 报告失败但论文仍可用时的降级原因 |
| `resolved_keyword` | 实际检索词；`RAG` 会扩展为 `retrieval-augmented generation` |
| `warnings` | 来源降级、缩写扩展、mock 模式等提示 |
| `recalled_memories` | 可做成"它想起了…"的小提示条（演示长期记忆很有用） |
| `degraded` / `degrade_reason` | `true` 时顶部显示降级提示：`LLM_ERROR`=大脑离线；`MCP_TIMEOUT`/`MCP_ERROR`=检索挂了 |

一次请求耗时：不检索约 1–3 秒，触发检索约 5–15 秒（取决于上游）。**建议发送后立即把输入框置灰并显示"Navi 正在找论文…"**。

### 情绪契约（Q 版形象动画映射）

`emotion` 只有这 6 个值，请按表做动作：

| emotion | 触发时机 | 建议动作 |
|---|---|---|
| `idle` | 默认 / 等待输入 | 轻微呼吸 + 偶尔眨眼 |
| `thinking` | 正在检索论文 | 眼睛看上方、头顶转圈 |
| `happy` | 正常回答完毕 | 微笑、身体弹一下 |
| `excited` | 检索到结果且命中长期兴趣 | 眼睛发光、跳两下 |
| `confused` | 降级（模型或检索挂了） | 歪头 + 问号气泡 |
| `sleepy` | 空闲超过 3 分钟 | 前端本地计时即可，不用问后端 |

口型：按 `reply` 文本长度做定时嘴部开合就行，后端不提供音画同步数据。
**最少实现 3 个状态（idle / thinking / happy）也能完整演示。**

---

## 二·补、智能体设置与 Skill

性格、语音参数和 Skill CRUD 见 `docs/V04_API.md`。启用的 Skill 命中触发词后会注入本轮系统提示词，响应通过 `skills_used` 返回实际使用的 Skill。

## 三、长期记忆 `/api/memory`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/memory?limit=100` | 记忆列表（按权重×新鲜度排序） |
| POST | `/api/memory` | `{content, mem_type?}` 手动新增（"记住我喜欢中文回答"） |
| DELETE | `/api/memory/{id}` | 删一条（用户纠正记错的地方） |
| POST | `/api/memory/clear` | 清空 |

`mem_type` 取值：`profile_fact`（身份/阶段）、`interest`（研究方向）、`preference`（偏好）、`goal`（目标）、`constraint`（不要做什么）。
列表项字段：`{id, mem_type, content, weight, hit_count, source_id, created_at, last_seen_at}`，`source_id=session:xxx` 说明它是从哪次对话抽出来的，`user_manual` 说明是用户自己写的。

---

## 四、用户画像 `/api/profile`

`GET /api/profile`（`?refresh=true` 强制重算）→

```json
{
  "status": "success",
  "has_enough_data": true,
  "sample_size": 7,
  "version": 3,
  "updated_at": "2026-09-22T01:20:31Z",
  "profile": {
    "domains":   [{"name": "图神经网络", "weight": 1.0}, {"name": "推荐系统", "weight": 0.86}],
    "interests": [{"tag": "知识图谱", "weight": 0.86, "trend": "up"}],
    "activity":  {"total_searches": 3, "total_messages": 12, "active_days": 2,
                  "last_active_at": "2026-09-22T01:12:44Z",
                  "daily_counts": [{"date": "2026-09-22", "n": 9}]},
    "style":     {"avg_question_len": 14.5, "prefers_chinese": true,
                  "asks_for_papers": 0.25, "wants_papers": true,
                  "summary": "研究图神经网络与推荐系统，关注知识图谱，求最新论文并询问入门方向。"},
    "top_keywords": [{"term": "graph neural network", "display": "图神经网络", "weight": 1.0, "times": 4}]
  }
}
```

**⚠️ `has_enough_data: false`（样本 <5 条行为）时，必须显示"数据不足，多聊几次就有了"占位卡片，不许画雷达图/词云。** 这是产品硬规则，评委问起来要能答。

- `domains` → 条形图或雷达图（领域分布）
- `interests[].trend` → `up/down/flat`，可做上升/下降箭头
- `activity.daily_counts` → 活跃度日历/柱状（最近 14 天）
- `style.summary` → 一句话风格描述（未接模型时为空字符串，**空就别显示这一块**）
- `GET /api/profile/searches?limit=20` → 我的检索记录列表

---

## 五、知识图谱页

用 `/api/kg/*` 那组接口（**不鉴权**），详见 `docs/KG_HANDOFF.md`。图谱由第三方同学实现，你只需要在页面里给它留一个挂载点（iframe 或组件位）。他没做完时，那个区域显示"图谱加载中"占位即可。

---

## 六、错误码（前端文案对照）

| error_code | HTTP | 建议文案 | 可重试 |
|---|---|---|---|
| `USER_EXISTS` | 400 | 该用户名已被注册 | 否 |
| `WEAK_PASSWORD` | 400 | 密码至少 6 位 | 否 |
| `BAD_CREDENTIALS` | 401 | 用户名或密码不正确 | 否 |
| `UNAUTHORIZED` | 401 | 请先登录 | 跳登录页 |
| `TOKEN_EXPIRED` | 401 | 登录已过期，请重新登录 | 跳登录页 |
| `NOT_FOUND` | 404 | 找不到该会话/记忆 | 否 |
| `EMPTY_MESSAGE` | 400 | 消息不能为空 | 否 |
| `MESSAGE_TOO_LONG` | 400 | 消息太长了 | 否 |
| `UPSTREAM_ERROR` | 503 | 服务暂时不可用，稍后再试 | **是** |
| `INVALID_REQUEST` | 400 | 请求参数不正确 | 否 |

每个响应头都有 `X-Request-ID`，报错时把它带上，我这边能凭它查日志。

---

## 七、建议的页面流程

```
启动 → localStorage 有 token？
        ├─ 有 → GET /api/auth/me（401 就清掉跳登录页）
        └─ 无 → 登录/注册页
首页 → POST /api/chat/sessions（或复用上次会话）
     → POST /api/chat/message（循环）
     → 退出时可不调 close（下次开新会话时后端也会自动整理记忆）
我的 → 画像页 / 记忆管理页 / 检索记录 / 知识图谱页
```

不需要 SSE/流式：当前是普通 POST，一次返回完整回复。打字机效果前端自己按字吐就行。
