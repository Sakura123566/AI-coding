# Research Navigator · 科研对话工作台

科研探索与研究导航智能体全栈实现。**输入研究主题 → 检索论文 → 生成研究导航报告 → 多轮对话与证据回溯**。仓库包含 FastAPI 后端与 Vue 3 前端。

当前版本：**v0.4.0**。主检索、报告、用户系统、对话、记忆、画像和知识图谱契约均已跑通。
真实模型已接 DeepSeek（`deepseek-chat`），`/api/health` 里 `llm_ready=true`；未配置 MCP 时使用 arXiv/OpenAlex 等真实来源自动降级。

v0.4.0 增量：姓名/年龄/身份跨设备持久化；长期知识图谱、对话回溯、利弊分析、节点删除与一键清空；智能体性格、语音参数和用户 Skill；真实行为周报 JSON 与中文 PDF。

v0.3.0 增量：科研对话会同时返回并持久化真实 `papers`、结构化 `report`、`resolved_keyword` 和 `warnings`；`RAG`、`GNN` 等常见英文缩写会扩展为完整检索词；新增 Docker、生产配置门禁和持久卷部署。

---

## 一、5 分钟跑起来

### 前端工作台

```bash
cd frontend
npm install
cp .env.example .env       # Windows: copy .env.example .env
npm run dev
```

前端默认通过 Vite 代理访问 `http://127.0.0.1:8000`。公网构建时把 `VITE_API_BASE_URL` 设置为后端 HTTPS 地址。

### 后端本机开发

```bash
# 1) 建虚拟环境并安装依赖（只需一次）
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux

# 2) 复制配置（默认就是能跑的离线模式）
cp .env.example .env

# 3) 启动
.venv/Scripts/python -m uvicorn backend.main:app --reload --port 8000

# 4) 自检
curl http://127.0.0.1:8000/api/health
```

- Swagger 自测页：<http://127.0.0.1:8000/docs>
- v0.4 新接口说明：`docs/V04_API.md`
- 健康检查：`GET /api/health` → `{"status":"ok", ...}`
- 主接口：`POST /api/research/run`
- 科研对话：`POST /api/chat/message`（科研意图会直接返回结构化报告）

### Docker / 公网容器

```bash
cp .env.production.example .env
docker compose up --build -d
```

生产环境必须设置真实 `AUTH_SECRET`、准确的前端 `CORS_ORIGINS`、模型密钥，并给 `/app/backend/data` 挂持久卷。完整步骤见 `docs/DEPLOYMENT.md`。

一键冒烟测试（自己拉服务、跑 6 个场景、保存契约样例）：

```bash
python scripts/smoke_test.py                # 离线 mock 数据
python scripts/smoke_test.py --source arxiv # 真实 arXiv 检索（本机已验证通过）
```

---

## 二、接口契约（已冻结）

```http
POST /api/research/run
Content-Type: application/json

{"keyword":"Graph Neural Networks","limit":10}
```

| 场景 | 返回 |
|---|---|
| 成功 | `status=success` + `papers[]` + `report{overview,themes,research_trends,reading_path,exploration_questions,limitations}` |
| 无结果 | `status=success`、`count=0`、`papers=[]`、`message="没有找到论文…"` |
| 检索失败 | HTTP 504（超时）/ 502（不可用）+ `status=error` + `error_code=MCP_TIMEOUT / MCP_ERROR` |
| 报告失败 | `status=success` + 真实 `papers` + `report=null` + `report_error="报告生成失败：…"` |
| 空输入 | HTTP 400 + `error_code=EMPTY_KEYWORD` |

完整字段说明、空值兜底、前端状态机见 **`docs/API_HANDOFF.md`**（直接发给队员2）。
可直接喂给前端的样例 JSON 在 **`docs/contract/`**（`success.json` / `success_arxiv.json` / `success_mock.json` / `empty.json` / `error.json` / `degraded.json`）。

---

## 三、配置（.env，全部走环境变量，密钥不进代码）

| 变量 | 默认 | 说明 |
|---|---|---|
| `PAPER_SOURCE` | `auto` | `auto`/`arxiv`/`openalex`/`semanticscholar`/`crossref`/`mock`/`mcp` |
| `PAPER_SOURCE_ORDER` | `arxiv,openalex,crossref` | auto 模式下的降级顺序 |
| `MCP_COMMAND` | 空 | 你们的 MCP 启动命令，如 `npx -y @modelcontextprotocol/server-arxiv` |
| `MCP_TOOL_NAME` | 空 | 留空则自动挑名字带 search/paper/arxiv 的工具。**arXiv 被限流期间请显式填 `search_openalex`** |
| `LLM_PROVIDER` | `mock` | 改 `openai` 才会真正调模型 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | 任意 OpenAI 兼容端点都行 |
| `LLM_API_KEY` | 空 | **只放 .env**，不进前端、不进仓库 |
| `LLM_MODEL` | `gpt-4o-mini` | 按你们能用的模型改 |
| `LLM_JSON_MODE` | `true` | 端点不支持 `response_format` 就设 `false` |
| `CACHE_ENABLED` | `true` | 同一主题重复请求直接返回上次结果，演示时防止重复烧模型 |
| `CACHE_TTL` | `600` | 缓存有效期（秒） |
| `CACHE_MAX_ENTRIES` | `64` | 缓存条数上限，超出按最近最少使用淘汰 |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

### 接真实模型（第5步）— ✅ 已接好

当前 `.env` 里已是 DeepSeek：`LLM_PROVIDER=openai` + `LLM_BASE_URL=https://api.deepseek.com/v1` + `LLM_MODEL=deepseek-chat`，JSON 模式实测可用。
**密钥只写在本地 `.env`，`.gitignore` 已排除，不要提交、不要贴到前端或 PPT 里。**
换模型只需改这三个变量，下面是各平台对照：

**模型密钥是什么？** 就是你去一家大模型平台注册后、在控制台里生成的一串字符（通常 `sk-` 开头）。后端拿它去调模型生成"研究导航报告"。它只在后端 `.env` 里，不会进前端、不会进仓库。

拿哪家都行，只要是 **OpenAI 兼容**的接口（即 `.../v1/chat/completions`）：

| 平台 | LLM_BASE_URL | 参考模型 | 备注 |
|---|---|---|---|
| DeepSeek 开放平台 | `https://api.deepseek.com/v1` | `deepseek-chat` | 便宜，中文好用 |
| 硅基流动 SiliconFlow | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-7B-Instruct` | 有免费额度，适合练手 |
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | 走兼容模式 |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | 有免费版 |
| OpenAI 官方 | `https://api.openai.com/v1` | `gpt-4o-mini` | 需要海外网络与外币卡 |

拿到之后填三个变量即可：

```bash
# .env
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.deepseek.com/v1     # 换成你那家的地址
LLM_API_KEY=sk-xxxxxxxxxxxx                 # 换成你那家的密钥
LLM_MODEL=deepseek-chat
```
重启后 `GET /api/health` 里 `llm_ready` 应为 `true`；如果端点不支持 `response_format`，把 `LLM_JSON_MODE` 设成 `false`。

### 接论文检索 MCP（第4步）

**两种形态都支持，填哪个就走哪个：**

| 形态 | 你要填的 | 例子 |
|---|---|---|
| 网址端点型（托管 MCP，把 URL 填进工具的那种） | `MCP_URL` | `https://mcp.xxx.com/xxx/mcp`、`.../sse`、`ws://127.0.0.1:8080/mcp?token=xxx` |
| 本地命令型（npx / python 启动） | `MCP_COMMAND` | `npx -y @modelcontextprotocol/server-arxiv` |

`MCP_TRANSPORT=auto` 时自动识别：`ws://`/`wss://` → **WebSocket**；地址带 `sse` → SSE；其他 → HTTP；填了命令 → stdio。

三步走：

```bash
# 1) 先看这个端点上有哪些工具、参数叫什么（不需要知道工具名也能跑）
python scripts/verify_source.py --source mcp --url "ws://127.0.0.1:8080/mcp?token=你的token" --list-tools

# 2) 真跑一次检索，确认能拿到论文
python scripts/verify_source.py "Graph Neural Networks" --source mcp --url "ws://..." --limit 5

# 3) 通了之后写进 .env，重启后端
#    PAPER_SOURCE=mcp / MCP_URL=... / MCP_TOOL_NAME=...（可选）/ MCP_AUTH_TOKEN=...（如需鉴权）
```

**IntelliConnect MCP Manager 用户的注意点**：
- 端点是 `ws://` 开头 → 走 WebSocket，本仓库已支持（依赖 `websocket-client`）；
- **URL 里的 token 必须完整复制**（`?token=` 后面一整个，别漏字符）；
- 演示时那个管理器程序必须开着、且已 Connect，否则后端拿不到论文（有降级：可把 `PAPER_SOURCE_ORDER` 里的 arxiv 留作兜底）。

MCP 返回字段会自动按常见别名（title/authors/year/abstract/url）归一化；字段名很特殊的话，改 `backend/sources/base.py` 的 `FIELD_ALIASES`。

**没有真实端点也能先把这条路跑通**：`python scripts/fake_mcp_server.py --port 8199` 会起一个本地假 MCP（返回的是假论文，仅限联调，别拿去演示）。

### 不想依赖第三方 MCP 管理器？三条路

企划案 MVP 写的是"调用论文 MCP…至少一个稳定来源"。如果你的 MCP 管理器不稳定/拿不到 token，有三条替代路：

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| **① 自建本地 MCP Server（当前默认）** | `scripts/local_paper_mcp_server.py`，把 arXiv / Semantic Scholar / Crossref 的官方 API 包成标准 MCP 工具（`search_arxiv` 等） | 后端确实走 **MCP 协议**调用工具；零新依赖；不依赖任何 GUI 程序；换电脑照样跑 | 工具是我们自己写的，讲解时要说清是"自建 MCP Server" |
| ② 后端直连论文 API | `PAPER_SOURCE=arxiv` | 最简单、最快 | 严格说不是 MCP，评委若卡这条会吃亏 |
| ③ 接第三方管理器（IntelliConnect 等） | 填它的 `ws://...?token=...` | 用现成工具，故事更好讲 | 依赖那个程序开着；token 拿到才能用 |

当前 `.env` 用的是 **① + ② 组合**：`PAPER_SOURCE_ORDER=mcp,arxiv,semanticscholar,crossref`
→ 先走 MCP 协议调本地 `search_arxiv` 工具，**MCP 挂了自动降级直连 arXiv**，演示不会白屏（降级会写进 `warnings` 字段）。

验证这两条路：

```bash
# 看自建 MCP Server 暴露了哪些工具
python scripts/verify_source.py --source mcp \
  --command "python scripts/local_paper_mcp_server.py" --list-tools

# 真跑一次
python scripts/verify_source.py "Graph Neural Networks" --source mcp \
  --command "python scripts/local_paper_mcp_server.py" --tool search_arxiv --limit 5
```

---

## 四、目录结构

```
backend/
  main.py            # FastAPI 入口：/api/health、/api/research/run、统一错误出口
  config.py          # 环境变量配置（自带极简 .env 加载器，无额外依赖）
  schemas.py         # 前后端契约（改名=违约，必须先打招呼）
  pipeline.py        # 检索→报告→降级 的主流程编排
  sources/           # 论文来源适配层（统一成 title/authors/year/abstract/url/source）
    arxiv.py  openalex.py  semanticscholar.py  crossref.py  mock.py
    mcp_stdio.py     # 本地命令型 MCP
    mcp_http.py      # 网址端点型 MCP（Streamable HTTP / SSE）
    mcp_ws.py        # WebSocket 型 MCP（ws://...?token=...）
    mcp_common.py    # 三种 MCP 共用的挑工具/拼参数/洗数据
  llm/
    client.py        # OpenAI 兼容 Chat Completions（只用标准库）
    prompts.py       # 要求严格 JSON 的提示词
    report.py        # 解析→校验→重试一次→失败抛错
    translate.py     # 中文主题 → 英文检索词（映射表 → 模型 → 原文）
  cache.py           # 内存结果缓存：同一主题不重复检索、不重复烧模型
  logging_setup.py   # 日志格式 + 请求 ID（排障用）
  db.py              # SQLite：连接、建表、时间工具（8 张表，文件在 backend/data/app.db）
  auth.py            # PBKDF2 密码哈希 + 手写 HS256 JWT + current_user 依赖
  errors.py          # 用户系统的统一错误出口（ApiError + 错误码表）
  repo.py            # 数据访问层：所有 SQL 都在这里
  engines/
    persona.py       # Q版人设 + 情绪契约 + 上下文组装 + 提示词注入防护
    chat_engine.py   # 意图识别 → 记忆召回 → 组上下文 → 生成 → 情绪 → 落库
    keyword_engine.py# 关键词抽取（模型 / 规则兜底）+ 权重公式 + 清洗
    memory_engine.py # 长期记忆：抽取、衰减、召回
    profile_engine.py# 用户画像：统计代码算 + 风格模型归纳
    llm_json.py      # 让模型输出结构化 JSON 的统一入口
  routers/
    auth_api.py      # /api/auth/*      注册 / 登录 / me / logout
    chat_api.py      # /api/chat/*      会话与对话
    memory_api.py    # /api/memory/*    长期记忆查看与删除
    profile_api.py   # /api/profile/*   画像与检索记录
    kg_api.py        # /api/kg/*        知识图谱对接（他人实现图谱）
scripts/
  verify_source.py   # 第1步：单独验证检索工具（含 MCP，--list-tools 可看工具有哪些）
  smoke_test.py      # 一键冒烟：6 个场景 + 生成契约样例
  local_paper_mcp_server.py  # 自建 MCP Server：把 arXiv/S2/Crossref 包成标准 MCP 工具
  fake_mcp_server.py # 本地假 MCP（假数据，仅用于联调"填网址端点"这条路）
  validate_fixes.py  # 验证第 1 轮评审的 5 项修改是否生效
  verify_user_system.py      # 用户系统端到端验证（49 项，含"重启后数据还在"）
docs/
  企划书_对话智能体与用户系统.md  # 用户系统的完整企划书（范围/架构/契约/排期）
  CHAT_API.md        # 给队员2：对话 / 登录 / 记忆 / 画像接口 + 情绪契约
  KG_HANDOFF.md      # 给知识图谱负责人：对接契约（拉取式）
  contract/kg_*.json # 图谱样例：keywords / events / cooccurrence
  contract/chat_message_sample.json / profile_sample.json
  API_HANDOFF.md     # 给队员2 的交接文档
  REFACTOR_PLAN.md   # 第 1 轮评审后的改造企划书
  REVIEW_ROUND2.md   # 二次检查报告 + 产品化差距估算
  contract/*.json    # 给队员3 的契约样例
                     # success.json / success_real.json / success_arxiv.json
                     # success_mock.json / empty.json / error.json / degraded.json
```

## 四·补、用户系统（对话 / 记忆 / 画像 / 图谱对接）

在"一次性报告工具"之上长出的 Q 版科研导航员。**零新依赖**：认证用标准库自签 JWT，
存储用 SQLite，模型调用复用原来的 `llm/client.py`。现有三个接口与契约字段**一行没改**。

一键验证（起真实服务、跑 49 项、最后还会重启一次验证真持久化）：

```bash
python scripts/verify_user_system.py                 # 离线 mock，可重复
python scripts/verify_user_system.py --real-model    # 用 .env 里的真模型跑一遍
```

| 模块 | 接口 | 说明 |
|---|---|---|
| 认证 | `/api/auth/register` `login` `me` `logout` | PBKDF2 存密码，JWT 默认 7 天 |
| 对话 | `/api/chat/sessions` `/message` `/close` | 意图识别（聊天/检索）+ 情绪输出 |
| 记忆 | `/api/memory` | 三层记忆：短期窗口 / 会话摘要 / 长期事实，可查看可删除 |
| 画像 | `/api/profile` `/searches` | 领域分布、兴趣趋势、活跃度、提问风格 |
| 图谱 | `/api/kg/keywords` `events` `cooccurrence` `health` | **拉取式**，知识图谱由他人实现 |

情绪契约（`emotion` 6 值：idle / thinking / happy / excited / confused / sleepy）见 `docs/CHAT_API.md` 第二节。
知识图谱对接契约见 `docs/KG_HANDOFF.md`。完整企划书见 `docs/企划书_对话智能体与用户系统.md`。

新增配置项（全部可省，默认值就能跑）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DB_PATH` | `backend/data/app.db` | SQLite 文件位置 |
| `AUTH_SECRET` | 开发用默认值 | **部署前必须改**，JWT 签名密钥 |
| `AUTH_TOKEN_TTL` | `604800` | token 有效期（秒） |
| `MIN_PASSWORD_LEN` | `6` | 密码最短长度 |
| `CHAT_WINDOW` | `6` | 短期上下文保留几轮 |
| `MEMORY_TOP_K` | `8` | 每轮最多注入多少条长期记忆 |
| `MEMORY_HALF_LIFE_DAYS` | `35` | 记忆新鲜度半衰期 |
| `PROFILE_MIN_SAMPLE` | `5` | 少于这个样本量，画像判定"数据不足" |
| `KG_MIN_TIMES` / `KG_MIN_WEIGHT` | `2` / `0.2` | 关键词对外暴露的下限 |

反假成功规则（跟主项目一致）：
- 样本不足时 `has_enough_data=false`，前端必须显示占位卡片，不许画雷达图；
- 模型挂了回 `degraded=true` + 真论文，**不拿模板句冒充 AI 回答**；
- `LLM_PROVIDER=mock` 时回复带【本地样例回复，未接入模型】前缀，`mode` 字段会写明 `mock`；
- 长期记忆每条都能追溯到某条消息或某次检索（`source_id`），用户可手动删除。

## 五、设计上的几条硬约束

- **运行依赖保持精简**：FastAPI/Uvicorn + ReportLab；检索与模型调用仍使用标准库 urllib，不存在大型 SDK 依赖。
- **不伪造成功**：检索失败就报错；报告失败就返回 `report=null` + `report_error`。
- **论文编号可追溯**：报告里的 `paper_ids` 只能是真实检索到的 P1…Pn，校验时会被过滤，编号对不上前端就能一眼看出。
- **中文主题先转英文再检索**（`backend/llm/translate.py`）：arXiv 不吃中文查询，不翻译就会一路兜底到 Crossref，捞回一堆"初中英语中考复习"式的不相关中文水刊，报告就成了假成功。映射表命中即用（零延迟），长句交给模型整句翻译，都失败才用原文。响应里 `keyword` 是用户原输入，`resolved_keyword` 是实际检索词。
- **所有来源都有超时**：HTTP `HTTP_TIMEOUT`，MCP 子进程 `MCP_TIMEOUT`，卡住不会拖死接口。
- **密钥只走环境变量**：前端拿不到，`.gitignore` 已排除 `.env`。
- **只缓存成功的结果**：有论文且报告没降级才进缓存；空结果、检索报错、报告失败一律不缓存，
  出问题刷新一次就是真的重试，不会把错误状态钉住 10 分钟（`CACHE_ENABLED=false` 可整体关闭）。
- **失败要能定位**：每次请求一个 ID，响应头 `X-Request-ID` 与日志里的 ID 一致；
  500 的异常细节只进服务端日志，不回给前端（异常文本里可能带端点 URL 或 token 片段）。

## 五·补、排障看哪里

日志走 stderr，格式 `时间 级别 [请求ID] 消息`，级别用 `LOG_LEVEL` 调。关键几条：

| 日志 | 含义 |
|---|---|
| `收到请求 keyword=... limit=...` | 请求进来了 |
| `来源 X 不可用，尝试下一个` | 某个论文源挂了，正在降级（同时会进 `warnings`） |
| `命中缓存，跳过检索与模型调用` | 没真跑，直接返回上次结果 |
| `流程结束 ... 耗时=xx.xs` | 一次完整流程的耗时，演示前看它估算等待时间 |
| `报告生成失败，保留论文列表` | 模型那步挂了，论文仍然真实 |
| `未捕获异常` + 堆栈 | 500 的完整堆栈，凭请求 ID 对得上 |

## 六、已知边界（演示时如实说）

- `mock` 源的论文和报告都是本地样例，页面和文档里都会标注，**不能拿来当真实演示**。
- Crossref 常返回书籍章节、摘要为空；arXiv 结果更贴合 AI/CS 方向，建议作为主源；
  **OpenAlex**（`backend/sources/openalex.py`）是主源挂掉时最靠谱的兜底：免费、无需密钥、限流宽松，
  论文质量明显好于 Crossref（实测同一主题，Crossref 捞回水刊，OpenAlex 头一条就是该方向的奠基论文）。
- **arXiv 会限流封 IP（HTTP 406）**：短时间内反复请求后，arXiv 会对本机 IP 返回 406，
  且不是换个 User-Agent 就能绕过（实测换浏览器 UA、加 `Accept` 头都无效，只能等它冷却，通常几十分钟到几小时）。
  表现是主源降级到 Crossref、论文质量明显变差。**演示前 1 小时别压测 arXiv**，
  并提前跑一次演示主题把结果缓存住（`CACHE_TTL` 临时调大），现场即使被限流也能秒回真实结果。
  Semantic Scholar 匿名调用也很容易 429，想稳就申请一个免费 API key。
- 模型归纳可能出错，报告里的 `limitations` 字段就是给用户的免责提示，不要删。
