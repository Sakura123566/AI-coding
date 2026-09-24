// 智能体设置服务层（前后端契约）。默认走 mock（VITE_USE_MOCK 未显式置 'false' 即为 mock）。
//
// 约定端点：
//   GET  /api/agent/settings  (Bearer) -> { settings: AgentSettings }   （后端用 ok(settings=...) 包裹）
//   PUT  /api/agent/settings  (Bearer, body: AgentSettingsPatch) -> { settings: AgentSettings }

import { type AgentSettings, type AgentSettingsPatch } from '../types/user'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
// 默认 mock：让「等后端」阶段的 UI 骨架也能直接演示。
const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'true') === 'true'

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

// 后端统一成功包 { status:'success', ... }；错误 { status:'error', error_code, message }
async function parseJson(res: Response): Promise<any> {
  const data = await res.json().catch(() => ({}))
  if (data?.status === 'error' || (!res.ok && data?.status !== 'success')) {
    throw new Error(data?.message || `请求失败（HTTP ${res.status}）`)
  }
  return data
}

const authHeaders = (token: string) => ({ Authorization: `Bearer ${token}` })

// —— mock 兜底 ——
const DEFAULT_SETTINGS: AgentSettings = {
  personality: 'rigorous_warm',
  tone: 'professional',
  detail_level: 'balanced',
  language: 'zh-CN',
  voice_enabled: true,
  voice_auto_play: false,
  voice_name: 'xiaoyan',
  voice_rate: 1.0,
  voice_pitch: 1.0,
  custom_instructions: '',
  agent_address_name: ''
}
let mockSettings: AgentSettings = { ...DEFAULT_SETTINGS }

// 从后端包裹结构中取 settings（兼容 {settings} 或裸对象）
function extractSettings(data: any): AgentSettings {
  return (data?.settings ?? data) as AgentSettings
}

// —— 读取设置 ——
export async function getAgentSettings(token: string): Promise<AgentSettings> {
  if (USE_MOCK) {
    await delay(300)
    return { ...mockSettings }
  }
  const res = await fetch(`${API_BASE}/api/agent/settings`, { headers: authHeaders(token) })
  const data = await parseJson(res)
  return extractSettings(data)
}

// —— 更新设置 ——
export async function putAgentSettings(
  token: string,
  patch: AgentSettingsPatch
): Promise<AgentSettings> {
  if (USE_MOCK) {
    await delay(300)
    mockSettings = { ...mockSettings, ...patch }
    return { ...mockSettings }
  }
  const res = await fetch(`${API_BASE}/api/agent/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(patch)
  })
  const data = await parseJson(res)
  return extractSettings(data)
}
