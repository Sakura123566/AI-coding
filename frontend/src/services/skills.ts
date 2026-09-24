// 用户自定义 Skill 服务层（前后端契约）。默认走 mock（VITE_USE_MOCK 未显式置 'false' 即为 mock）。
//
// 约定端点（backend/routers/agent_api.py，前缀 /api/agent）：
//   GET    /skills            (Bearer) -> { skills: Skill[], count }
//   POST   /skills            (Bearer, body: SkillInput)  -> { skill: Skill }
//   PATCH  /skills/{id}       (Bearer, body: SkillPatch)  -> { skill: Skill }
//   DELETE /skills/{id}       (Bearer) -> { deleted, skill_id }
//
// 注意：后端 SkillBody 中 instruction 为必填（技能的执行指令/行为描述）。

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'true') === 'true'

export interface Skill {
  id: number
  name: string
  description: string
  instruction: string
  triggers: string[]
  enabled: boolean
}

export interface SkillInput {
  name: string
  description?: string
  instruction: string // 必填：技能的执行指令/行为描述
  triggers: string[]
  enabled?: boolean
}

export type SkillPatch = Partial<SkillInput>

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

async function parseJson(res: Response): Promise<any> {
  const data = await res.json().catch(() => ({}))
  if (data?.status === 'error' || (!res.ok && data?.status !== 'success')) {
    throw new Error(data?.message || `请求失败（HTTP ${res.status}）`)
  }
  return data
}

const authHeaders = (token: string) => ({ Authorization: `Bearer ${token}` })

// triggers 兼容后端返回的 JSON 字符串或数组
function normalizeTriggers(t: unknown): string[] {
  if (Array.isArray(t)) return t.map(String)
  if (typeof t === 'string' && t.trim()) {
    try {
      const parsed = JSON.parse(t)
      if (Array.isArray(parsed)) return parsed.map(String)
    } catch {
      /* 不是 JSON，按逗号/空白拆分 */
    }
    return t
      .split(/[,，\s]+/)
      .map((s) => s.trim())
      .filter(Boolean)
  }
  return []
}

function normalizeSkill(row: any): Skill {
  return {
    id: row.id,
    name: row.name ?? '',
    description: row.description ?? '',
    instruction: row.instruction ?? '',
    triggers: normalizeTriggers(row.triggers),
    enabled: !!row.enabled
  }
}

// —— mock 兜底 ——
let mockSeq = 3
const mockSkills: Skill[] = [
  {
    id: 1,
    name: '论文精读',
    description: '对指定论文做结构化精读与要点提炼',
    instruction: '当用户要求精读/拆解某篇论文时，按「背景-方法-结果-局限」结构输出。',
    triggers: ['精读', '拆解论文', '论文解析'],
    enabled: true
  },
  {
    id: 2,
    name: '方向调研',
    description: '围绕关键词给出研究现状与路线图',
    instruction: '当用户要做方向调研时，先给现状概览，再列 3-5 条可行路线。',
    triggers: ['调研', '研究现状', '路线图'],
    enabled: true
  },
  {
    id: 3,
    name: '术语翻译',
    description: '把英文术语翻译成中文并给通俗解释',
    instruction: '遇到英文专业术语时，先给中文译名再给一句通俗解释。',
    triggers: ['翻译', '什么意思', '术语'],
    enabled: false
  }
]

export async function listSkills(token: string): Promise<Skill[]> {
  if (USE_MOCK) {
    await delay(300)
    return mockSkills.map((s) => ({ ...s }))
  }
  const res = await fetch(`${API_BASE}/api/agent/skills`, { headers: authHeaders(token) })
  const data = await parseJson(res)
  return (data?.skills ?? []).map(normalizeSkill)
}

export async function createSkill(token: string, input: SkillInput): Promise<Skill> {
  if (USE_MOCK) {
    await delay(300)
    const s: Skill = {
      id: ++mockSeq,
      name: input.name,
      description: input.description ?? '',
      instruction: input.instruction,
      triggers: input.triggers ?? [],
      enabled: input.enabled ?? true
    }
    mockSkills.push(s)
    return { ...s }
  }
  const res = await fetch(`${API_BASE}/api/agent/skills`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(input)
  })
  const data = await parseJson(res)
  return normalizeSkill(data?.skill)
}

export async function updateSkill(token: string, id: number, patch: SkillPatch): Promise<Skill> {
  if (USE_MOCK) {
    await delay(250)
    const s = mockSkills.find((x) => x.id === id)
    if (!s) throw new Error('技能不存在')
    Object.assign(s, patch)
    return { ...s }
  }
  const res = await fetch(`${API_BASE}/api/agent/skills/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(patch)
  })
  const data = await parseJson(res)
  return normalizeSkill(data?.skill)
}

export async function deleteSkill(token: string, id: number): Promise<void> {
  if (USE_MOCK) {
    await delay(250)
    const i = mockSkills.findIndex((x) => x.id === id)
    if (i >= 0) mockSkills.splice(i, 1)
    return
  }
  const res = await fetch(`${API_BASE}/api/agent/skills/${id}`, {
    method: 'DELETE',
    headers: authHeaders(token)
  })
  await parseJson(res)
}
