# Research Navigator 前端实施契约

## 产品结构

- 品牌统一为 `Research Navigator`，助手名为 `Navi`。
- 一级导航：探索、历史、资料库、画像、图谱。
- 画像页内部分为“画像”和“记忆”。
- 资料库中的收藏标记为“本机收藏”，只写 `localStorage`。
- 游客可调用 `/api/research/run`；进入对话、历史、画像、记忆时要求登录。

## API 基址

- 前端只读取 `import.meta.env.VITE_API_BASE_URL`。
- 本地开发可设为 `http://127.0.0.1:8000`，或配置 Vite 代理。
- 生产构建必须指向公网 HTTPS 后端。
- 禁止在源码中出现 `http://127.0.0.1:8000` 默认值。

## 主流程

1. 游客输入主题，调用 `POST /api/research/run`，渲染论文、报告和 `resolved_keyword`。
2. 登录后创建会话：`POST /api/chat/sessions`。
3. 发送消息：`POST /api/chat/message`。
4. 科研意图响应会同时携带：
   - `papers`：完整论文对象。
   - `report`：方向概览、主题簇、趋势、阅读路线、追问、局限。
   - `report_error`：报告降级原因。
   - `resolved_keyword`：实际检索词。
   - `warnings`：来源降级、缓存、mock 等提示。
   - `degraded` / `degrade_reason`：能力降级状态。
5. 历史消息接口中的每条助手消息带 `payload`，刷新后可恢复论文与报告，不需要重新请求模型。

## RAG 歧义

- 输入精确的 `RAG` 时，前端先显示两个选项：
  - `RAG · 检索增强生成`
  - `RAG · 免疫基因`
- 选择检索增强生成后发送 `retrieval-augmented generation`。
- 选择免疫基因后发送 `RAG gene`。
- 后端也把精确的 `RAG`/`GNN` 扩展到 AI 领域完整词，并在 `resolved_keyword` 与 `warnings` 中说明。
- 结果区显示“实际检索词”，并提供“修改检索词后重试”。

## UI 状态

- 初始：介绍、示例主题、登录入口。
- 检索中：只显示“正在检索并组织报告”，不得按固定计时宣称已找到论文。
- 成功：显示论文数量、实际检索词、论文证据、结构化报告。
- 无结果：显示平台原因为空的状态，不绘制空报告。
- 报告降级：论文正常显示，报告区域显示 `report_error`。
- 模型降级：顶部或消息内展示 `degraded` 原因。
- 失败：保留输入与重试按钮，显示 `X-Request-ID` 便于定位。
- mock：显示“本地样例模式”，不得让用户误认为真实模型结果。

## 响应式与无障碍

- `>= 1280px`：左会话栏、中对话/报告、右证据栏。
- `768–1279px`：右侧证据栏改为抽屉。
- `< 768px`：单栏与底部导航，输入框宽度不低于可用区域的 90%。
- 图标按钮必须有 `aria-label`。
- 异步状态容器使用 `aria-live="polite"`。
- 键盘可完成登录、检索、选论文、切报告、删除记忆。
- 动画遵守 `prefers-reduced-motion`。