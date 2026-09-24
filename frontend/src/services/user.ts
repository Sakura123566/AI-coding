// 用户鉴权 + 资料服务层（前后端契约）。
// 默认走 mock（VITE_USE_MOCK 未显式置 'false' 即为 mock），用于先把 UI 跑通；
// 后端接入后把 VITE_USE_MOCK 置 'false' 即可切换，无需改 UI 代码。
//
// 约定端点：
//   POST /api/auth/register  { username, password, display_name? } -> AuthResult
//   POST /api/auth/login     { username, password }                -> AuthResult
//   GET  /api/auth/me        (Bearer)                             -> { user, token_ttl }
//   PATCH /api/auth/me       { display_name?, real_name?, age?, identity?, avatar_id? } -> { user }
//   GET  /api/profile        (Bearer)                             -> UserPortrait

import {
  type AuthResult,
  type LoginInput,
  type ProfileUpdate,
  type RegisterInput,
  type User,
  type UserPortrait
} from '../types/user'

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

// —— mock 数据 ——
let mockUser: User | null = null
let mockPortrait: UserPortrait | null = null

function mockUserFrom(input: RegisterInput | LoginInput, extra?: Partial<User>): User {
  const display_name =
    'display_name' in input && input.display_name ? input.display_name : input.username
  return {
    id: Math.floor(Math.random() * 1e9),
    username: input.username,
    display_name,
    real_name: null,
    age: null,
    identity: null,
    avatar_id: 'navi',
    created_at: new Date().toISOString(),
    last_login_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...extra
  }
}

function mockPortraitFor(u: User): UserPortrait {
  return {
    has_enough_data: true,
    sample_size: 12,
    version: 1,
    updated_at: new Date().toISOString(),
    profile: {
      domains: [
        { name: '机器学习', weight: 0.92 },
        { name: '知识图谱', weight: 0.81 },
        { name: '文献综述', weight: 0.64 }
      ],
      interests: [
        { tag: '图神经网络', weight: 0.7, trend: 'up' },
        { tag: '检索增强生成', weight: 0.55, trend: 'flat' },
        { tag: '对比学习', weight: 0.4, trend: 'down' }
      ],
      activity: {
        total_searches: 8,
        total_messages: 23,
        active_days: 5,
        last_active_at: new Date().toISOString(),
        daily_counts: []
      },
      style: {
        avg_question_len: 24.5,
        prefers_chinese: true,
        asks_for_papers: 0.6,
        summary: `${u.display_name} 是一位对前沿研究保持好奇的探索者，喜欢在「知识派对」里快速锁定方向、沉淀知识。`
      },
      top_keywords: [{ term: 'gnn', display: '图神经网络', weight: 0.7, times: 6 }]
    }
  }
}

// —— 注册 ——
export async function register(input: RegisterInput): Promise<AuthResult> {
  if (USE_MOCK) {
    await delay(500)
    const user = mockUserFrom(input)
    mockUser = user
    mockPortrait = mockPortraitFor(user)
    return { token: 'mock-token-' + user.id, token_type: 'Bearer', expires_in: 3600, user_id: user.id, user }
  }
  const res = await fetch(`${API_BASE}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input)
  })
  const data = await parseJson(res)
  return {
    token: data.token,
    token_type: data.token_type || 'Bearer',
    expires_in: data.expires_in || 0,
    user_id: data.user_id,
    user: data.user
  }
}

// —— 登录 ——
export async function login(input: LoginInput): Promise<AuthResult> {
  if (USE_MOCK) {
    await delay(500)
    const user = mockUserFrom(input)
    mockUser = user
    mockPortrait = mockPortraitFor(user)
    return { token: 'mock-token-' + user.id, token_type: 'Bearer', expires_in: 3600, user_id: user.id, user }
  }
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input)
  })
  const data = await parseJson(res)
  return {
    token: data.token,
    token_type: data.token_type || 'Bearer',
    expires_in: data.expires_in || 0,
    user_id: data.user_id,
    user: data.user
  }
}

// —— 当前用户（GET /api/auth/me）——
export async function getMe(token: string): Promise<User> {
  if (USE_MOCK) {
    await delay(300)
    const u = mockUser ?? mockUserFrom({ username: 'guest', password: '' }, { display_name: '访客' })
    mockUser = u
    return u
  }
  const res = await fetch(`${API_BASE}/api/auth/me`, { headers: authHeaders(token) })
  const data = await parseJson(res)
  return data.user
}

// —— 用户画像（GET /api/profile）——
export async function getPortrait(token: string): Promise<UserPortrait> {
  if (USE_MOCK) {
    await delay(300)
    const u = mockUser ?? mockUserFrom({ username: 'guest', password: '' }, { display_name: '访客' })
    mockPortrait = mockPortrait ?? mockPortraitFor(u)
    return mockPortrait
  }
  const res = await fetch(`${API_BASE}/api/profile`, { headers: authHeaders(token) })
  const data = await parseJson(res)
  return {
    has_enough_data: !!data.has_enough_data,
    sample_size: data.sample_size || 0,
    version: data.version || 1,
    updated_at: data.updated_at || '',
    profile: data.profile
  }
}

// —— 更新资料（PATCH /api/auth/me）——
export async function updateProfile(token: string, patch: ProfileUpdate): Promise<User> {
  if (USE_MOCK) {
    await delay(300)
    const u = mockUser ?? mockUserFrom({ username: 'guest', password: '' })
    mockUser = { ...u, ...patch }
    return mockUser
  }
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(patch)
  })
  const data = await parseJson(res)
  return data.user
}

export async function logout(token: string): Promise<void> {
  if (USE_MOCK) {
    await delay(150)
    mockUser = null
    return
  }
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: 'POST',
    headers: authHeaders(token)
  }).catch(() => {})
}
