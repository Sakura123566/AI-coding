// 用户与鉴权相关数据模型 + 前后端契约类型定义（对齐 backend/routers/auth_api.py + profile_api.py）。
//
// 后端统一响应包：{ status: 'success', ...extra }；错误：{ status: 'error', error_code, message }。
//
// 鉴权：
//   POST /api/auth/register  { username, password, display_name? } -> AuthResult
//   POST /api/auth/login     { username, password }                -> AuthResult
//   GET  /api/auth/me        (Authorization: Bearer <token>)        -> { user: User, token_ttl }
//   PATCH /api/auth/me       { display_name?, real_name?, age?, identity?, avatar_id? } -> { user }
// 画像：
//   GET /api/profile         (Authorization: Bearer <token>)        -> { has_enough_data, sample_size, version, updated_at, profile: UserPortrait }

// 登录身份可选预设（仅 UI 方便，后端 identity 是自由字符串 ≤60）
export const IDENTITY_PRESETS: { value: string; label: string }[] = [
  { value: 'student', label: '学生' },
  { value: 'postgrad', label: '研究生' },
  { value: 'teacher', label: '教师' },
  { value: 'researcher', label: '研究员' },
  { value: 'engineer', label: '工程师' },
  { value: 'other', label: '其他' }
]

export function identityLabel(value: string | null | undefined): string {
  if (!value) return '—'
  return IDENTITY_PRESETS.find((p) => p.value === value)?.label || value
}

// public_user 返回结构（snake_case 与后端一致，避免映射层）
export interface User {
  id: number
  username: string
  display_name: string
  real_name: string | null
  age: number | null
  identity: string | null
  avatar_id: string
  created_at: string
  last_login_at: string | null
  updated_at: string | null
}

export interface AuthResult {
  token: string
  token_type: string
  expires_in: number
  user_id: number
  user: User
}

export interface RegisterInput {
  username: string
  password: string
  display_name?: string
}

export interface LoginInput {
  username: string
  password: string
}

export interface ProfileUpdate {
  display_name?: string
  real_name?: string
  age?: number
  identity?: string
  avatar_id?: string
}

export type PortraitTrend = 'up' | 'down' | 'flat'

// 用户画像（GET /api/profile 的 profile 字段）
export interface UserPortrait {
  has_enough_data: boolean
  sample_size: number
  version: number
  updated_at: string
  profile: {
    domains: { name: string; weight: number }[]
    interests: { tag: string; weight: number; trend: PortraitTrend }[]
    activity: {
      total_searches: number
      total_messages: number
      active_days: number
      last_active_at: string | null
      daily_counts: { date: string; n: number }[]
    }
    style: {
      avg_question_len: number
      prefers_chinese: boolean
      asks_for_papers: number
      summary: string
    }
    top_keywords: { term: string; display: string; weight: number; times: number }[]
  }
}

// —— 智能体设置（GET/PUT /api/agent/settings）——
// 对齐 backend/routers/agent_api.py 的 AgentSettingsBody 字段与枚举。
export type AgentPersonality =
  | 'rigorous_warm'
  | 'concise_socratic'
  | 'creative_companion'
  | 'strict_reviewer'
  | 'custom'
export type AgentTone = 'professional' | 'friendly' | 'concise' | 'encouraging'
export type AgentDetailLevel = 'brief' | 'balanced' | 'deep'
export type AgentLanguage = 'zh-CN' | 'en'

export const AGENT_PERSONALITY_LABELS: Record<AgentPersonality, string> = {
  rigorous_warm: '严谨而温暖',
  concise_socratic: '简洁苏格拉底式',
  creative_companion: '创意伙伴',
  strict_reviewer: '严格评审',
  custom: '自定义'
}
export const AGENT_TONE_LABELS: Record<AgentTone, string> = {
  professional: '专业',
  friendly: '亲切',
  concise: '简练',
  encouraging: '鼓励'
}
export const AGENT_DETAIL_LABELS: Record<AgentDetailLevel, string> = {
  brief: '精简',
  balanced: '适中',
  deep: '深入'
}
export const AGENT_LANGUAGE_LABELS: Record<AgentLanguage, string> = {
  'zh-CN': '中文',
  en: '英文'
}

export interface AgentSettings {
  personality: AgentPersonality
  tone: AgentTone
  detail_level: AgentDetailLevel
  language: AgentLanguage
  voice_enabled: boolean
  voice_auto_play: boolean
  voice_name: string
  voice_rate: number // 0.5 - 2.0
  voice_pitch: number // 0.5 - 2.0
  custom_instructions: string // ≤ 2000
}

// PUT 允许部分字段
export type AgentSettingsPatch = Partial<AgentSettings>

// —— 周报（GET /api/reports/weekly）——
export interface WeeklyReport {
  week_start: string
  week_end: string
  report: Record<string, unknown>
  cached: boolean
}
