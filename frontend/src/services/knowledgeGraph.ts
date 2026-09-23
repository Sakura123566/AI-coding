// 知识图谱（探索型 / 记忆型）前后端契约与数据层。
// 前端只调用约定的 REST 端点，不接触模型密钥 / MCP（由后端完成）。
//
// 约定的后端端点（待接入，见各函数 TODO）：
//   探索型：
//     POST /api/graph/generate  { keyword, tone, sentences, limit } -> GraphData
//     POST /api/graph/parse      { text, tone, sentences }            -> GraphData
//   记忆型：
//     GET    /api/memory          -> MemoryNode[]
//     POST   /api/memory          -> MemoryNode   (新增)
//     PATCH  /api/memory/:id      -> 更新内容 / 锁定状态
//     DELETE /api/memory/:id      -> 删除
//     POST   /api/memory/:id/lock { locked }       -> 锁定 / 解锁
//     POST   /api/memory/simulate -> 模拟一轮对话，返回新增 MemoryNode[]
//
// 后端未就绪期间默认走 mock（VITE_USE_MOCK 未显式置为 'false' 即为 mock），
// 用于先把 UI 骨架与交互跑通；后端接入后把 VITE_USE_MOCK 置 'false' 即可切换。

export type GraphNodeType = 'concept' | 'paper' | 'method' | 'dataset' | 'application'
export type GraphLayout = 'web' | 'radial' | 'timeline'
export type GraphTone = 'professional' | 'plain'
export type MemoryKind = 'inspiration' | 'question'

export interface GraphNode {
  id: string
  label: string
  type: GraphNodeType
  importance: 1 | 2 | 3
  desc: string
  year?: number
  isCenter?: boolean
}
export interface GraphEdge {
  from: string
  to: string
  relation?: string
}
export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  generatedKeyword?: string
}
export interface MemoryNode {
  id: string
  kind: MemoryKind
  title: string
  detail: string
  locked: boolean
  createdAt: number
}
export interface GenerateGraphOptions {
  tone: GraphTone
  sentences: 1 | 2 | 3
  limit?: number
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
// 默认 mock：让「等后端」阶段的 UI 骨架也能直接演示。
const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'true') === 'true'

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

// —— 探索型：生成网络 ——
export async function generateGraph(keyword: string, opts: GenerateGraphOptions): Promise<GraphData> {
  if (USE_MOCK) {
    const { mockGraphForKeyword } = await import('../mocks/knowledgeGraph.mock')
    await delay(500)
    return { ...mockGraphForKeyword(keyword || '知识图谱'), generatedKeyword: keyword || '知识图谱' }
  }
  // TODO(backend): POST /api/graph/generate
  const res = await fetch(`${API_BASE}/api/graph/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      keyword,
      tone: opts.tone,
      sentences: opts.sentences,
      limit: opts.limit ?? 30
    })
  })
  if (!res.ok) throw new Error(`生成知识图谱失败（HTTP ${res.status}）`)
  return normalizeGraph(await res.json())
}

// —— 探索型：解析文章 ——
export async function parseArticle(text: string, opts: GenerateGraphOptions): Promise<GraphData> {
  if (USE_MOCK) {
    const { mockGraphForKeyword } = await import('../mocks/knowledgeGraph.mock')
    await delay(500)
    return { ...mockGraphForKeyword('解析文章'), generatedKeyword: '解析文章' }
  }
  // TODO(backend): POST /api/graph/parse
  const res = await fetch(`${API_BASE}/api/graph/parse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, tone: opts.tone, sentences: opts.sentences })
  })
  if (!res.ok) throw new Error(`解析文章失败（HTTP ${res.status}）`)
  return normalizeGraph(await res.json())
}

// —— 记忆型：读取 / 新增 / 更新 / 删除 / 锁定 / 模拟对话 ——
export async function fetchMemories(): Promise<MemoryNode[]> {
  if (USE_MOCK) {
    const { mockMemories } = await import('../mocks/knowledgeGraph.mock')
    await delay(300)
    return mockMemories()
  }
  // TODO(backend): GET /api/memory
  const res = await fetch(`${API_BASE}/api/memory`, { method: 'GET' })
  if (!res.ok) throw new Error(`加载记忆失败（HTTP ${res.status}）`)
  return (await res.json()) as MemoryNode[]
}

export async function saveMemory(node: MemoryNode): Promise<MemoryNode> {
  if (USE_MOCK) {
    await delay(150)
    return node
  }
  // TODO(backend): POST /api/memory
  const res = await fetch(`${API_BASE}/api/memory`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(node)
  })
  if (!res.ok) throw new Error(`保存记忆失败（HTTP ${res.status}）`)
  return (await res.json()) as MemoryNode
}

export async function updateMemory(id: string, patch: Partial<MemoryNode>): Promise<void> {
  if (USE_MOCK) {
    await delay(120)
    return
  }
  // TODO(backend): PATCH /api/memory/:id
  await fetch(`${API_BASE}/api/memory/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch)
  })
}

export async function deleteMemory(id: string): Promise<void> {
  if (USE_MOCK) {
    await delay(120)
    return
  }
  // TODO(backend): DELETE /api/memory/:id
  await fetch(`${API_BASE}/api/memory/${id}`, { method: 'DELETE' })
}

export async function toggleMemoryLock(id: string, locked: boolean): Promise<void> {
  if (USE_MOCK) {
    await delay(100)
    return
  }
  // TODO(backend): POST /api/memory/:id/lock { locked }
  await fetch(`${API_BASE}/api/memory/${id}/lock`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ locked })
  })
}

export async function simulateMemoryRound(): Promise<MemoryNode[]> {
  if (USE_MOCK) {
    const { mockSimulateRound } = await import('../mocks/knowledgeGraph.mock')
    await delay(400)
    return mockSimulateRound()
  }
  // TODO(backend): POST /api/memory/simulate
  const res = await fetch(`${API_BASE}/api/memory/simulate`, { method: 'POST' })
  if (!res.ok) throw new Error(`模拟对话失败（HTTP ${res.status}）`)
  return (await res.json()) as MemoryNode[]
}

// —— 字段归一化：后端返回结构可能略有差异，统一成前端使用的字段 ——
function normalizeGraph(raw: any): GraphData {
  const nodes: GraphNode[] = Array.isArray(raw?.nodes)
    ? raw.nodes.map((n: any) => ({
        id: String(n?.id ?? ''),
        label: String(n?.label ?? n?.name ?? '节点'),
        type: (['concept', 'paper', 'method', 'dataset', 'application'].includes(n?.type)
          ? n.type
          : 'concept') as GraphNodeType,
        importance: (n?.importance === 1 || n?.importance === 2 || n?.importance === 3
          ? n.importance
          : 2) as 1 | 2 | 3,
        desc: String(n?.desc ?? n?.description ?? ''),
        year: n?.year ? Number(n.year) : undefined,
        isCenter: !!n?.isCenter
      }))
    : []
  const ids = new Set(nodes.map((n) => n.id))
  const edges: GraphEdge[] = Array.isArray(raw?.edges)
    ? raw.edges
        .map((e: any) => ({
          from: String(e?.from ?? e?.source ?? ''),
          to: String(e?.to ?? e?.target ?? ''),
          relation: e?.relation ? String(e.relation) : undefined
        }))
        .filter((e: GraphEdge) => ids.has(e.from) && ids.has(e.to))
    : []
  return { nodes, edges, generatedKeyword: raw?.generatedKeyword ? String(raw.generatedKeyword) : undefined }
}
