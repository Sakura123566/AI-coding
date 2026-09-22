# Research Navigator 公网部署说明

## 目标拓扑

- 前端：静态站或容器，构建时设置 `VITE_API_BASE_URL=https://api.example.com`。
- 后端：FastAPI 单容器，监听 `0.0.0.0:8000`，由平台提供 HTTPS。
- 数据库：SQLite 文件挂载到持久卷 `/app/backend/data`。
- 模型：密钥只存在后端平台的 Secret 环境变量中。

## 必填生产环境变量

| 变量 | 要求 |
|---|---|
| `ENVIRONMENT` | 必须是 `production` |
| `HOST` | `0.0.0.0` |
| `PORT` | `8000` |
| `DB_PATH` | `/app/backend/data/app.db` |
| `AUTH_SECRET` | 长随机字符串，禁止使用开发默认值 |
| `CORS_ORIGINS` | 精确前端 Origin，逗号分隔，禁止 `*` |
| `LLM_PROVIDER` | `openai` |
| `LLM_BASE_URL` | 例如 `https://api.deepseek.com/v1` |
| `LLM_API_KEY` | 平台 Secret，不提交仓库 |
| `LLM_MODEL` | 例如 `deepseek-chat` |
| `CACHE_TTL` | 演示前建议 `21600` 秒 |

`ENVIRONMENT=production` 时，如果仍在用开发 `AUTH_SECRET` 或 CORS 为 `*`，服务会拒绝启动。这是刻意设置的生产门禁。

## 容器平台部署

1. 将后端目录作为项目根目录创建 Docker 服务。
2. 构建使用仓库根目录 `Dockerfile`。
3. 容器端口填写 `8000`。
4. 持久卷挂载到 `/app/backend/data`。
5. 配置上表环境变量，模型密钥放平台 Secret。
6. 健康检查路径使用 `GET /api/health`，期望 HTTP 200 且 `status=ok`。
7. 平台开启 HTTPS，并把最终 API 域名写入前端构建变量。

本机验证容器：

```powershell
Copy-Item .env.production.example .env
# 修改 .env 中的域名、AUTH_SECRET 和模型密钥
powershell -ExecutionPolicy Bypass -File scripts/docker_up.ps1
```

## 验收命令

```bash
curl -fsS https://api.example.com/api/health
curl -fsS -X POST https://api.example.com/api/research/run \
  -H "Content-Type: application/json" \
  -d '{"keyword":"RAG","limit":3}'
```

第二条响应的 `resolved_keyword` 应为 `retrieval-augmented generation`。重启容器后，注册用户、会话、报告、记忆和画像必须仍存在。