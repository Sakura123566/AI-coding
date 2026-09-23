# Research Navigator v0.4 后端接口

## 1. 跨设备个人资料

`PATCH /api/auth/me`

```json
{
  "display_name": "张三",
  "real_name": "张三",
  "age": 22,
  "identity": "计算机专业研究生",
  "avatar_id": "navi"
}
```

资料写入 SQLite，并同步写入高权重长期记忆。只要后端数据库挂载持久卷，用户换电脑重新登录后仍能读取。

## 2. 智能体设置

### `GET /api/agent/settings`
### `PUT /api/agent/settings`

```json
{
  "personality": "strict_reviewer",
  "tone": "professional",
  "detail_level": "deep",
  "language": "zh-CN",
  "voice_enabled": true,
  "voice_auto_play": true,
  "voice_name": "Microsoft Xiaoxiao",
  "voice_rate": 1.0,
  "voice_pitch": 1.0,
  "custom_instructions": "回答必须区分事实、推断和不确定项。"
}
```

`personality` 支持：`rigorous_warm`、`concise_socratic`、`creative_companion`、`strict_reviewer`、`custom`。

语音播放使用浏览器 Web Speech API。后端持久化参数，并在科研对话响应中返回 `voice` 字段，不依赖云端 TTS 密钥。

## 3. 用户 Skill

- `GET /api/agent/skills`
- `POST /api/agent/skills`
- `PATCH /api/agent/skills/{skill_id}`
- `DELETE /api/agent/skills/{skill_id}`

```json
{
  "name": "实验设计检查",
  "description": "检查实验变量、对照与指标",
  "instruction": "回答实验问题时必须写清自变量、因变量、对照组和评价指标。",
  "triggers": ["实验", "对照", "指标"],
  "enabled": true
}
```

没有 triggers 的 Skill 是常驻 Skill；有 triggers 时，只有用户消息命中才注入提示词。

## 4. 长期知识图谱

所有个人图谱接口必须登录，`user_id` 不再由客户端指定。

### `GET /api/kg/map`

返回根节点、关键词节点和共现边：

```json
{
  "root": {"id": "root", "label": "我的研究", "type": "root"},
  "nodes": [{"id": 1, "term": "graph neural networks", "label": "图神经网络", "weight": 0.8}],
  "edges": [{"source": "graph neural networks", "target": "recommender systems", "weight": 2}],
  "counts": {"nodes": 1, "edges": 1}
}
```

### `GET /api/kg/nodes/{node_id}`

返回该关键词的搜索记录、原始问答、对应会话和已有分析。

### `POST /api/kg/nodes/{node_id}/analysis?refresh=true`

生成或刷新：

- `summary`
- `pros`
- `cons`
- `next_steps`
- `mode`: `llm` 或 `heuristic`

### `DELETE /api/kg/nodes/{node_id}`

删除该关键词节点、相关事件和缓存分析。

### `POST /api/kg/clear`

一键清空当前用户全部图谱节点与事件，不删除聊天历史和账号记忆。

## 5. 周报

### `GET /api/reports/weekly?week_start=YYYY-MM-DD&refresh=false`

返回真实行为统计、关键词、关键问答和 AI/规则生成的周报 JSON。

### `GET /api/reports/weekly.pdf?week_start=YYYY-MM-DD`

返回中文 PDF，使用 ReportLab 内置 `STSong-Light` 字体映射，不依赖系统字体文件。

周报内容包括：本周总结、主要进展、学习脉络、关键问答、做得好的地方、需要改进和下周计划。

## 6. 环境变量

```env
REPORT_TIMEZONE_OFFSET_HOURS=8
```

所有数据坚持服务端 SQLite 持久化。生产部署必须给 `/app/backend/data` 挂持久卷，否则更换电脑可以登录，但容器重建后数据会丢失。
## 7. 论文摘要中文化

每篇 `papers[]` 会新增：

```json
{
  "title_zh": "中文标题",
  "abstract": "原始英文摘要",
  "abstract_zh": "忠实中文翻译或压缩翻译",
  "abstract_summary_zh": "默认展示的 60-120 字中文短摘要",
  "translation_status": "translated",
  "translation_note": null
}
```

`translation_status` 取值：`translated`、`original_chinese`、`unavailable`、`not_requested`。模型不可用时保留英文并标记 `unavailable`，不伪造翻译。报告生成和对话上下文优先使用中文短摘要，降低 token 消耗。
