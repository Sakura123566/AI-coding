// 用户登录态：user / portrait / token / isLoggedIn，持久化到 localStorage（刷新不丢登录）。
// 与 knowledgeParty.ts 同样的持久化写法，便于维护。
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import {
  register as apiRegister,
  login as apiLogin,
  logout as apiLogout,
  getMe as apiGetMe,
  getPortrait as apiGetPortrait,
  updateProfile as apiUpdateProfile
} from '../services/user'
import type { LoginInput, ProfileUpdate, RegisterInput, User, UserPortrait } from '../types/user'

// 升到 v2：用户结构从旧 email/name 改为真实 public_user（username/display_name/...），旧数据不兼容。
const STORAGE_KEY = 'kp-user-v2'

interface PersistShape {
  token: string
  user: User | null
  portrait: UserPortrait | null
}

function loadState(): PersistShape | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    return {
      token: String(data?.token ?? ''),
      user: (data?.user as User) ?? null,
      portrait: (data?.portrait as UserPortrait) ?? null
    }
  } catch {
    return null
  }
}

export const useUserStore = defineStore('user', () => {
  const saved = loadState()
  const token = ref<string>(saved?.token ?? '')
  const user = ref<User | null>(saved?.user ?? null)
  const portrait = ref<UserPortrait | null>(saved?.portrait ?? null)
  const loading = ref(false)
  const error = ref('')

  const isLoggedIn = computed(() => !!token.value && !!user.value)

  // 拉取/刷新用户 + 画像（打开资料面板时调用；后端就绪后即为真实数据）
  async function fetchProfile() {
    if (!token.value) return
    loading.value = true
    try {
      const [u, p] = await Promise.all([apiGetMe(token.value), apiGetPortrait(token.value)])
      user.value = u
      portrait.value = p
    } catch (e) {
      // 拉取失败不阻塞 UI，保留现有资料
      console.warn('[user] fetchProfile failed', e)
    } finally {
      loading.value = false
    }
  }

  async function login(input: LoginInput) {
    loading.value = true
    error.value = ''
    try {
      const res = await apiLogin(input)
      token.value = res.token
      user.value = res.user
      await fetchProfile()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '登录失败'
    } finally {
      loading.value = false
    }
  }

  async function register(input: RegisterInput) {
    loading.value = true
    error.value = ''
    try {
      const res = await apiRegister(input)
      token.value = res.token
      user.value = res.user
      await fetchProfile()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '注册失败'
    } finally {
      loading.value = false
    }
  }

  // 完善资料（PATCH /api/auth/me）
  async function saveProfile(patch: ProfileUpdate) {
    if (!token.value || !user.value) return
    loading.value = true
    error.value = ''
    try {
      const u = await apiUpdateProfile(token.value, patch)
      user.value = u
      await fetchProfile()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '保存失败'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    if (token.value) {
      try {
        await apiLogout(token.value)
      } catch {
        /* ignore */
      }
    }
    token.value = ''
    user.value = null
    portrait.value = null
  }

  // 应用启动时若已有 token，异步刷新用户 + 画像
  function init() {
    if (token.value) fetchProfile()
  }

  watch(
    [token, user, portrait],
    () => {
      const data: PersistShape = { token: token.value, user: user.value, portrait: portrait.value }
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
      } catch {
        /* ignore */
      }
    },
    { deep: true }
  )

  return { token, user, portrait, loading, error, isLoggedIn, login, register, logout, fetchProfile, saveProfile, init }
})
