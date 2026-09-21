# Research Navigator · 后端（队员1）

科研探索与研究导航智能体的后端雏形。**输入研究主题 → 检索论文 → 生成研究导航报告 → 返回统一 JSON**。

当前状态：**第2–7 步全部跑通**（健康检查 ✅、契约 JSON ✅、真实检索 ✅、真实模型报告 ✅、降级 ✅、交接文档 ✅）。
真实模型已接 DeepSeek（`deepseek-chat`），`/api/health` 里 `llm_ready=true`。
唯一还空着的是 **MCP 端点 URL**——把你们那个"填网址"的 MCP 地址给我，一条命令就能验证并接上；不接也能正常演示（当前走 arXiv 真实检索）。

---

## 一、5 分钟跑起来

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
- 健康检查：`GET /api/health` → `{"status":"ok", ...}`
- 主接口：`POST /api/research/run`

一键冒烟测试（自己拉服务、跑 8 个场景、保存契约样例）：

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
| 检索失败 | `status=error` + `error_code=MCP_TIMEOUT / MCP_ERROR` |
| 报告失败 | `status=success` + 真实 `papers` + `report=null` + `report_error="报告生成失败：…"` |
| 空输入 | HTTP 400 + `error_code=EMPTY_KEYWORD` |

完整字段说明、空值兜底、前端状态机见 **`docs/API_HANDOFF.md`**（直接发给队员2）。
可直接喂给前端的样例 JSON 在 **`docs/contract/`**（`success.json` / `success_arxiv.json` / `success_mock.json` / `empty.json` / `error.json` / `degraded.json`）。

---

## 三、配置（.env，全部走环境变量，密钥不进代码）

| 变量 | 默认 | 说明 |
|---|---|---|
| `PAPER_SOURCE` | `auto` | `auto`/`arxiv`/`semanticscholar`/`crossref`/`mock`/`mcp` |
| `PAPER_SOURCE_ORDER` | `arxiv,semanticscholar,crossref` | auto 模式下的降级顺序 |
| `MCP_COMMAND` | 空 | 你们的 MCP 启动命令，如 `npx -y @modelcontextprotocol/server-arxiv` |
| `MCP_TOOL_NAME` | 空 | 留空则自动挑名字带 search/paper/arxiv 的工具 |
| `LLM_PROVIDER` | `mock` | 改 `openai` 才会真正调模型 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | 任意 OpenAI 兼容端点都行 |
| `LLM_API_KEY` | 空 | **只放 .env**，不进前端、不进仓库 |
| `LLM_MODEL` | `gpt-4o-mini` | 按你们能用的模型改 |
| `LLM_JSON_MODE` | `true` | 端点不支持 `response_format` 就设 `false` |

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
    arxiv.py  semanticscholar.py  crossref.py  mock.py
    mcp_stdio.py     # 本地命令型 MCP
    mcp_http.py      # 网址端点型 MCP（Streamable HTTP / SSE）
    mcp_common.py    # 两种 MCP 共用的挑工具/拼参数/洗数据
  llm/
    client.py        # OpenAI 兼容 Chat Completions（只用标准库）
    prompts.py       # 要求严格 JSON 的提示词
    report.py        # 解析→校验→重试一次→失败抛错
scripts/
  verify_source.py   # 第1步：单独验证检索工具（含 MCP，--list-tools 可看工具有哪些）
  smoke_test.py      # 一键冒烟：8 个场景 + 生成契约样例
  fake_mcp_server.py # 本地假 MCP（假数据，仅用于联调"填网址端点"这条路）
docs/
  API_HANDOFF.md     # 给队员2 的交接文档
  contract/*.json    # 给队员3 的契约样例
```

## 五、设计上的几条硬约束

- **依赖只有 fastapi + uvicorn**，检索和模型调用全用标准库 urllib，装包失败的风险最小。
- **不伪造成功**：检索失败就报错；报告失败就返回 `report=null` + `report_error`。
- **论文编号可追溯**：报告里的 `paper_ids` 只能是真实检索到的 P1…Pn，校验时会被过滤，编号对不上前端就能一眼看出。
- **中文主题先转英文再检索**（`backend/llm/translate.py`）：arXiv 不吃中文查询，不翻译就会一路兜底到 Crossref，捞回一堆"初中英语中考复习"式的不相关中文水刊，报告就成了假成功。映射表命中即用（零延迟），长句交给模型整句翻译，都失败才用原文。响应里 `keyword` 是用户原输入，`resolved_keyword` 是实际检索词。
- **所有来源都有超时**：HTTP `HTTP_TIMEOUT`，MCP 子进程 `MCP_TIMEOUT`，卡住不会拖死接口。
- **密钥只走环境变量**：前端拿不到，`.gitignore` 已排除 `.env`。

## 六、已知边界（演示时如实说）

- `mock` 源的论文和报告都是本地样例，页面和文档里都会标注，**不能拿来当真实演示**。
- Crossref 常返回书籍章节、摘要为空；arXiv 结果更贴合 AI/CS 方向，建议作为主源。
- 模型归纳可能出错，报告里的 `limitations` 字段就是给用户的免责提示，不要删。
