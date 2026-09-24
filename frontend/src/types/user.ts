// 用户与鉴权相关数据模型 + 前后端契约类型定义。
//
// 后端接口（待接入，见 services/user.ts 的 TODO）：
//   POST /api/auth/register  { email, password, name, age?, identity? } -> AuthResult
//   POST /api/auth/login     { email, password }                        -> AuthResult
//   GET  /api/user/profile   (Authorization: Bearer <token>)            -> User（含 profile 用户画像）

export type UserIdentity =
  | 'student' // 学生
  | 'postgrad' // 研究生
  | 'teacher' // 教师
  | 'researcher' // 研究员
  | 'engineer' // 工程师
  | 'other' // 其他

export const IDENTITY_LABELS: Record<UserIdentity, string> = {
  student: '学生',
  postgrad: '研究生',
  teacher: '教师',
  researcher: '研究员',
  engineer: '工程师',
  other: '其他'
}

// 用户画像：后端动态生成，前端只负责展示（后端就绪前用 mock 占位）。
export interface UserProfile {
  summary?: string // 一句话画像
  facets?: { label: string; value: string }[] // 维度化画像（兴趣 / 活跃时段 / 常用功能…）
  tags?: string[] // 关键词标签
}

export interface User {
  id: string
  email: string
  name: string // 姓名
  age?: number // 年龄
  identity?: UserIdentity // 身份
  avatar?: string // 头像 URL（mock 用首字母圆形代替）
  bio?: string // 个性签名
  profile?: UserProfile // 用户画像（后端提供）
  createdAt?: number
}

export interface AuthResult {
  token: string
  user: User
}

export interface RegisterInput {
  email: string
  password: string
  name: string
  age?: number
  identity?: UserIdentity
}

export interface LoginInput {
  email: string
  password: string
}
