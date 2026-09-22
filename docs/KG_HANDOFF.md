> **v0.4 更新**：个人知识图谱接口现在必须登录，客户端不再传任意 `user_id`；新增图谱、节点、利弊分析、删除和清空接口。最新契约见 `docs/V04_API.md`，本文件保留为 v0.3 第三方对接参考。

# 知识图谱对接文档（给知识图谱负责人）

版本：v1.0 ｜ 日期：2026-09-22 ｜ 提供方：队员1（后端）
状态：**接口已实现并跑通**，样例数据可现取。

---

## 一、我给你什么，你给我什么

| 我（后端） | 你（知识图谱） |
|---|---|
| 抽好的关键词（带权重、类别、时间、来源证据） | 构图、存储、可视化 |
| 原始事件流（检索 + 对话原文），你想自己抽也行 | 节点/边的渲染与交互 |
| 关键词共现对（可直接当边） | 图谱页嵌到前端 |
| `/api/kg/health` 自检接口 | —— |

**我不做**：图数据库、图算法、可视化。你那边没做完不影响我，我这边慢了也不影响你——因为接口是**拉取式**的。

---

## 二、接口一览（无需鉴权，本机直连即可）

后端地址默认 `http://127.0.0.1:8000`（后端跑在哪台机器就用哪台；跨机器部署另说）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/kg/keywords` | 关键词（**推荐首选**） |
| GET | `/api/kg/events` | 原始事件流（检索 + 对话） |
| GET | `/api/kg/cooccurrence` | 关键词共现对（边） |
| GET | `/api/kg/health` | 自检：有多少词、多少事件、最近更新时间 |

所有响应统一结构：成功 `{"status":"success", ...}`，失败 `{"status":"error","error_code":...,"message":...}`。

---

## 三、`GET /api/kg/keywords`

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `user_id` | 空 | 不传 = 全用户聚合（一张全局图）；传了 = 只看这一个用户 |
| `limit` | 200 | 最多返回多少条 |
| `min_times` | 2 | 至少出现几次才返回（默认值已能滤掉噪声） |
| `min_weight` | 0.2 | 权重下限 |

响应：

```json
{
  "status": "success",
  "user_id": 1,
  "scope": "user",
  "count": 3,
  "generated_at": "2026-09-22T01:20:31Z",
  "keywords": [
    {
      "term": "graph neural network",
      "display": "图神经网络",
      "weight": 1.0,
      "category": "method",
      "times": 4,
      "first_seen": "2026-09-22T01:10:02Z",
      "last_seen": "2026-09-22T01:12:44Z",
      "sources": [
        {"type": "search", "id": "s3"},
        {"type": "chat", "id": "m57"}
      ]
    }
  ]
}
```

字段说明：

| 字段 | 含义 | 建议用法 |
|---|---|---|
| `term` | **归一化后的规范词**（小写、别名已合并） | **当作节点 ID**，同义词已合并成一个 |
| `display` | 展示用的词（保留用户原始写法） | 节点上的文字 |
| `weight` | 0~1，代码算出来的，不是模型报的 | 节点大小 / 颜色深浅 |
| `category` | `method` / `domain` / `dataset` / `task` / `other` | 节点分类着色 |
| `times` | 累计出现次数 | 节点权重参考 |
| `first_seen` / `last_seen` | 首次 / 最近出现时间（UTC ISO8601） | 时间轴、热度衰减 |
| `sources` | 证据：`search`=检索记录 id，`chat`=消息 id | 点击节点回溯到原文 |

**权重怎么来的（可解释，答辩用得上）：**

```
weight = 0.45 × 频率 + 0.35 × 新鲜度 + 0.20 × 来源可信度
频率     = log(1 + 出现次数) / log(1 + 该用户最高频词的次数)
新鲜度   = 0.5 ^ (距今天数 / 35)      # 半衰期 35 天
来源可信度 = 检索 1.0 / 对话 0.7        # 主动检索比随口提及更能代表兴趣
```

**同义词已经合并过了**，例如 `GNN / 图神经网络 / graph neural networks` 都会归到 `graph neural network` 这一个 term。合并表在 `backend/engines/keyword_engine.py` 的 `ALIASES`，**你要加新词直接告诉我，我改这张表**，不要在你那边做字符串匹配去重（两边各去一次会打架）。

---

## 四、`GET /api/kg/events`（原始事件流）

参数：`user_id`（可选）、`since`（ISO8601，可选）、`limit`（默认 200）。

```json
{
  "status": "success",
  "count": 2,
  "events": [
    {
      "type": "search", "id": "s3", "user_id": 1,
      "keyword": "图神经网络", "resolved_keyword": "graph neural network",
      "source": "openalex", "result_count": 8,
      "session_id": "s-9f2c1a3b", "created_at": "2026-09-22T01:10:02Z"
    },
    {
      "type": "chat", "id": "m57", "user_id": 1,
      "session_id": "s-9f2c1a3b", "text": "我在研究图神经网络在推荐系统上的应用",
      "intent": "chat", "created_at": "2026-09-22T01:11:20Z"
    }
  ]
}
```

---

## 五、`GET /api/kg/cooccurrence`（边）

参数：`user_id`（**必填**，共现按用户算）、`limit`（默认 100）。

```json
{
  "status": "success",
  "user_id": 1,
  "count": 3,
  "pairs": [
    {"source": "graph neural network", "target": "recommender system", "weight": 3},
    {"source": "graph neural network", "target": "knowledge graph", "weight": 1}
  ]
}
```

`weight` = 两个词在同一条来源（同一次检索 / 同一条消息）里共同出现的次数。节点名用的是**归一化后的 term**，与 `/keywords` 的 `term` 字段对齐，可以直接连。

---

## 六、`GET /api/kg/health`

```json
{"status":"ok","total_keywords":3,"total_events":9,"total_users":1,
 "last_keyword_at":"2026-09-22T01:12:44Z","contract_version":"1.0"}
```

你那边启动时先打这个接口，返回 `total_keywords = 0` 说明后端还没产生数据（正常，先去前端聊几句就有）。

---

## 七、更新频率与拉取建议

- 数据**实时写入**（每次检索、每条对话后立刻抽关键词落库），你轮询即可，不需要等批处理；
- 建议每 10~30 秒拉一次，或在你页面切到图谱时拉一次；
- 想做增量：记下上次拉到的 `last_seen`，用 `/events?since=...` 取新事件。

---

## 八、需要你确认的三件事（回我一下就行）

1. 你要**聚合后的关键词**还是**原始事件流**？（两个都给了，但我想知道你以哪个为准，方便我优先保证那个的质量）
2. 要不要**共现边**？要的话粒度按"同一次检索/同一条消息"算 OK 吗？
3. 是**按 user_id 分图**，还是**全用户一张图**？接口两种都支持，但我想把默认值设成你要的那个。

---

## 九、常见问题

**Q：为什么有的词只有英文没有中文？**
A：所有词都会归一化成一个规范 term（多为英文），中文原文放在 `display` 字段。展示用 `display`，做 ID 用 `term`。

**Q：权重一直变？**
A：权重含时间衰减项，同一个词今天和一周后取到的 weight 会不同。这是刻意的——兴趣会过期。做静态图的话可以只取一次快照存下来。

**Q：我能不能自己往里写数据？**
A：暂时不行，写入接口没开（避免双方互相污染数据）。你要加测试账号或造数据，告诉我，我从后端灌。

**Q：跨域会不会被拦？**
A：后端已开 CORS（`Access-Control-Allow-Origin: *`），前端页面直接 fetch 即可。
