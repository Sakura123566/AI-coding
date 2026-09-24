# 论文检索限流：成因与解决方案

日期：2026-09-24
范围：`PAPER_SOURCE=auto` 的多源检索链路（arXiv / OpenAlex / Crossref / Semantic Scholar / MCP）

---

## 一、问题是什么

实测日志里出现过三类限流，表现和成因完全不同：

| 来源 | 现象 | 真正原因 |
|---|---|---|
| arXiv | `HTTP 406 from export.arxiv.org`；有时直接 `SSL: UNEXPECTED_EOF_WHILE_READING` 挂住十几秒 | 共享出口 IP 请求过频被封；换 User-Agent 无效，只能等冷却 |
| OpenAlex | `HTTP 429`，响应体 `Anonymous search is temporarily rate-limited while the search cluster is under...` | 匿名调用没有进礼貌池；搜索集群压力大时优先掐匿名流量 |
| Semantic Scholar | `429` | 匿名调用几乎必然被限流，基本不可依赖 |

**最要命的不是报错，而是"挂住"**：arXiv 从被墙的网络里 SSL 握手会一直不返回，
一次检索就干等 20s+，哪怕另外三个源 3 秒就把结果拿回来了。

## 二、解决方案（三层）

### 第 1 层：源头减量——少打、打对

| 措施 | 说明 | 配置 |
|---|---|---|
| 填真实联系邮箱 | OpenAlex / Crossref 用它进"礼貌池"，限流优先级显著提高 | `SCHOLARLY_CONTACT_EMAIL=你的邮箱` |
| 去掉重复出口 | `MCP_TOOL_NAME=search_openalex` 时，`mcp` 和 `openalex` 打的是同一个 API。**两个都留着 = 每次检索把 OpenAlex 打两遍**，这是限流放大器 | `PAPER_SOURCE_ORDER=arxiv,crossref,openalex` |
| 结果落缓存 | 同一关键词 24 小时内不再打上游；演示前热身一次，现场几乎零请求 | `PAPER_CACHE_ENABLED=true` |

### 第 1.5 层：认清配额——匿名配额是按 IP 算的（实测重要）

2026-09-24 调试时实测到的行为，值得单独记一笔：

```
同一个 URL，间隔几秒连续请求：
  第 1 次  curl  mailto=test@example.com        -> HTTP 200
  第 2 次  curl  mailto=任意值                   -> HTTP 429 Too Many Requests
  第 3 次  python urllib（和代码同路径）          -> SSL: UNEXPECTED_EOF_WHILE_READING
```

结论：

1. **OpenAlex 的匿名配额是按出口 IP 算的**，不是按 mailto。填了邮箱能进礼貌池、
   拿更高的额度，但额度用完了照样 429——**换个假邮箱并不能绕过**；
2. 被限流之后，OpenAlex 对超限客户端的行为是**直接掐断 TLS 连接**，
   所以代码里看到的是 `SSL: UNEXPECTED_EOF_WHILE_READING` 而不是干净的 429。
   看到 SSL EOF **不要以为是网络问题，先怀疑配额用尽**；
3. 一个出口 IP（尤其共享出口/机房 IP）很容易被打满。**开发期间反复试同一个关键词
   就能把额度耗光**，之后所有源里就只剩 Crossref，而 Crossref 大多没有摘要——
   摘要覆盖率会从 6/6 掉到 2/6。这就是"报告突然变水了"的真实原因。

**应对**：靠缓存，不要靠重试。演示前热身一遍、现场搜同样的词命中缓存；
不要在现场反复试同一个关键词。

### 第 2 层：代码保护——arXiv 与其余源各有一套

**arXiv（`backend/sources/arxiv_client.py`）**：官方要求相邻请求间隔 ≥3 秒，所以是"排队 + 熔断"：

- 最小间隔 3s（`ARXIV_MIN_INTERVAL_SECONDS`）
- 429/406 后整条出口冷却 300s（`ARXIV_COOLDOWN_SECONDS`）
- 指数退避重试，听服务端的 `Retry-After`
- 连续失败 3 次熔断 120s，之后半开探测
- **限速状态存 SQLite**（`ARXIV_RATE_LIMIT_BACKEND=sqlite`）：MCP 每次调用会新拉一个子进程，
  纯内存锁管不到它，落 SQLite 才能让两个进程一起排队

**其余源（`backend/sources/throttle.py`）**：这些源不是"必须排队"，而是"被打中就换一个"：

- 429 后冷却该源（`SOURCE_COOLDOWN_SECONDS`），期间请求**快速失败**，调度层立刻换源，
  不让用户干等，也不去把限流越拖越长
- 可重试错误（429 / 5xx / 网络 / 超时）按 `Retry-After` + 指数退避重试
- 连续失败熔断，`SOURCE_CIRCUIT_COOLDOWN_SECONDS` 后半开

### 第 3 层：调度兜底——一个源挂了不影响整体

`backend/sources/orchestrator.py` 的并行调度：

- **宽限期**：只要有任一源返回结果，最多再等 `PAPER_SEARCH_GRACE_SECONDS`（默认 4s）就收工。
  **这一条是"挂住不返回"的正面解法**——卡住的源不再拖垮整次检索
- **总预算** `PAPER_SEARCH_BUDGET_SECONDS`（默认 30s）：到点放弃还没回来的源
- **单源上限** `PAPER_PROVIDER_TIMEOUT_SECONDS`（默认 12s）
- 单源失败只记一条告警，其他源的结果照常返回
- 全部失败才用**过期缓存**兜底，且标记 `stale`，绝不拿旧数据冒充实时结果

## 三、实测效果

改造前后对比（关键词 `graph neural networks`，真实网络）：

| 指标 | 改造前 | 改造后 |
|---|---|---|
| 论文重复 | 《A Comprehensive Survey on GNN》**出现两次** | 已合并为一条 |
| DOI 字段 | 全为空 | 10/10 有 DOI |
| 论文摘要 | 降级到 Crossref 时几乎全空，模型只能说"摘要为空，无法展开" | **6/6 有摘要**，且都带中文翻译 |
| 卡住的源 | 整次检索干等 20s+ | 宽限期到就放弃，不再拖垮整体 |

## 四、演示前的操作清单

1. **填邮箱**：`SCHOLARLY_CONTACT_EMAIL=` 填一个真实邮箱
2. **热身缓存**：把要演示的 2~3 个主题先各跑一次，让 SQLite 缓存暖起来
   ```bash
   curl -X POST http://127.0.0.1:8000/api/research/run \
        -H "Content-Type: application/json" \
        -d '{"keyword":"图神经网络","limit":10}'
   ```
   现场再搜同样的词会直接命中缓存，秒回，且完全绕开限流
3. **确认健康**：`GET /api/health` 里 `scholarly_contact_configured` 应为 `true`
4. **别现场调小** `ARXIV_MIN_INTERVAL_SECONDS`——那只会让封禁更长

## 五、排障：日志里看什么

```bash
# 限速与冷却
grep "限速等待\|进入冷却" backend.log

# 重试与放弃
grep "请求失败\|放弃等待" backend.log

# 摘要回填
grep "摘要回填" backend.log
```

| 日志 | 含义 | 该做什么 |
|---|---|---|
| `进入冷却 key=arxiv 时长=300s` | arXiv 被限流，已在冷却 | 正常，等冷却或换源 |
| `已有数据源返回结果，剩余源最多再等 4.0s` | 宽限期开始计时 | 正常 |
| `数据源 arxiv 未在宽限期内返回，已放弃等待` | arXiv 太慢被放弃 | 正常；若频繁出现可把它移出 `PAPER_SOURCE_ORDER` |
| `摘要回填 候选=N OpenAlex命中=M` | 摘要回填结果 | 命中少说明 OpenAlex 也没收录这些论文的摘要 |
| `SSL: UNEXPECTED_EOF_WHILE_READING`（api.openalex.org） | **多半是匿名配额耗尽**，不是网络故障 | 别重试，改用缓存；等配额恢复 |

## 六、已知边界

- 单实例部署 + SQLite 足够比赛场景；多实例要换成 Redis 之类的共享限速后端
- `SOURCE_RATE_LIMIT_BACKEND=memory` 时，MCP 子进程**不共享**冷却状态；
  需要跨进程共享就设成 `sqlite`（和 arXiv 一样）
- 配额是**按出口 IP** 的，所以本机开发跑太多会把演示也一起拖累——开发时尽量用 `PAPER_SOURCE=mock`