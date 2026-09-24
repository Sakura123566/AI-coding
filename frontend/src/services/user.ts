// 用户鉴权 + 资料服务层（前后端契约）。
// 默认走 mock（VITE_USE_MOCK 未显式置 'false' 即为 mock），用于先把 UI 跑通；
// 后端接入后把 VITE_USE_MOCK 置 'false' 即可切换，无需改 UI 代码。
//
// 约定端点：
//   POST /api/auth/register  { email, password, name, age?, identity? } -> AuthResult
//   POST /api/auth/login     { email, password }                        -> AuthResult
//   GET  /api/user/profile   (Authorization: Bearer <token>)            -> User（含 profile）

import {
  type AuthResult,
  type LoginInput,
  type RegisterInput,
  type User,
  type UserProfile
} from '../types/user'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
// 默认 mock：让「等后端」阶段的 UI 骨架也能直接演示。
const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'true') === 'true'

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

// —— mock 数据 ——
let mockCurrentUser: User | null = null

function mockProfile(name: string): UserProfile {
  return {
    summary: `${name} 是一位对前沿研究保持好奇的探索者，喜欢在「知识派对」里快速锁定方向、沉淀知识。`,
    facets: [
      { label: '研究兴趣', value: '机器学习 · 知识图谱 · 文献综述' },
      { label: '活跃时段', value: '晚间 20:00–23:00' },
      { label: '常用功能', value: '搜索 · 收藏 · 图谱' },
      { label: '偏好语言', value: '中文' }
    ],
    tags: ['好奇心强', '系统思维', '效率优先']
  }
}

function mockUserFromInput(input: LoginInput | RegisterInput, extra?: Partial<User>): User {
  const name =
    'name' in input && input.name ? input.name : input.email.split('@')[0] || '用户'
  return {
    id: 'u-' + Math.random().toString(36).slice(2, 10),
    email: input.email,
    name,
    age: extra?.age,
    identity: extra?.identity,
    avatar: '',
    bio: '',
    profile: mockProfile(name),
    createdAt: Date.now(),
    ...extra
  }
}

// —— 注册 ——
export async function register(input: RegisterInput): Promise<AuthResult> {
  if (USE_MOCK) {
    await delay(500)
    const user = mockUserFromInput(input, { age: input.age, identity: input.identity })
    mockCurrentUser = user
    return { token: 'mock-token-' + user.id, user }
  }
  // TODO(backend): POST /api/auth/register
  const res = await fetch(`${API_BASE}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input)
  })
  if (!res.ok) throw new Error(`注册失败（HTTP ${res.status}）`)
  return normalizeAuth(await res.json())
}

// —— 登录 ——
export async function login(input: LoginInput): Promise<AuthResult> {
  if (USE_MOCK) {
    await delay(500)
    const user = mockUserFromInput(input)
    mockCurrentUser = user
    return { token: 'mock-token-' + user.id, user }
  }
  // TODO(backend): POST /api/auth/login
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input)
  })
  if (!res.ok) throw new Error(`登录失败（HTTP ${res.status}）`)
  return normalizeAuth(await res.json())
}

// —— 拉取资料（含用户画像）——
export async function getProfile(token: string): Promise<User> {
  if (USE_MOCK) {
    await delay(350)
    // mock 直接返回登录时构造的用户（含 profile）；未登录则给个默认访客。
    return mockCurrentUser ?? mockUserFromInput({ email: 'guest@demo.com', password: '' }, { name: '访客' })
  }
  // TODO(backend): GET /api/user/profile
  const res = await fetch(`${API_BASE}/api/user/profile`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` }
  })
  if (!res.ok) throw new Error(`获取资料失败（HTTP ${res.status}）`)
  return normalizeUser(await res.json())
}

export async function logout(token: string): Promise<void> {
  if (USE_MOCK) {
    await delay(150)
    mockCurrentUser = null
    return
  }
  // TODO(backend): POST /api/auth/logout
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` }
  }).catch(() => {})
}

// —— 字段归一化：后端返回结构可能略有差异，统一成前端使用的字段 ——
function normalizeAuth(raw: any): AuthResult {
  return { token: String(raw?.token ?? ''), user: normalizeUser(raw?.user ?? raw) }
}
function normalizeUser(raw: any): User {
  return {
    id: String(raw?.id ?? ''),
    email: String(raw?.email ?? ''),
    name: String(raw?.name ?? raw?.email?.split('@')[0] ?? '用户'),
    age: raw?.age ? Number(raw.age) : undefined,
    identity: raw?.identity,
    avatar: raw?.avatar ? String(raw.avatar) : '',
    bio: raw?.bio ? String(raw.bio) : '',
    profile: raw?.profile
      ? {
          summary: raw.profile.summary ? String(raw.profile.summary) : undefined,
          facets: Array.isArray(raw.profile.facets)
            ? raw.profile.facets.map((f: any) => ({ label: String(f.label), value: String(f.value) }))
            : undefined,
          tags: Array.isArray(raw.profile.tags) ? raw.profile.tags.map((t: any) => String(t)) : undefined
        }
      : undefined,
    createdAt: raw?.createdAt ? Number(raw.createdAt) : undefined
  }
}
