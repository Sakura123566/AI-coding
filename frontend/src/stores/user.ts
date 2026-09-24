// 用户登录态：currentUser / token / isLoggedIn，持久化到 localStorage（刷新不丢登录）。
// 与 knowledgeParty.ts 同样的持久化写法，便于维护。
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import {
  register as apiRegister,
  login as apiLogin,
  logout as apiLogout,
  getProfile as apiGetProfile
} from '../services/user'
import type { LoginInput, RegisterInput, User } from '../types/user'

const STORAGE_KEY = 'kp-user-v1'

interface PersistShape {
  token: string
  user: User | null
}

function loadState(): PersistShape | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    return { token: String(data?.token ?? ''), user: (data?.user as User) ?? null }
  } catch {
    return null
  }
}

export const useUserStore = defineStore('user', () => {
  const saved = loadState()
  const token = ref<string>(saved?.token ?? '')
  const user = ref<User | null>(saved?.user ?? null)
  const loading = ref(false)
  const error = ref('')

  const isLoggedIn = computed(() => !!token.value && !!user.value)

  // 拉取/刷新用户画像（打开资料面板时调用；后端就绪后即为真实数据）
  async function fetchProfile() {
    if (!token.value) return
    try {
      const fresh = await apiGetProfile(token.value)
      // 用后端返回的最新字段覆盖（保留本地已有的基础信息）
      user.value = { ...(user.value as User), ...fresh, profile: fresh.profile ?? (user.value as User).profile }
    } catch (e) {
      // 拉取失败不阻塞 UI，保留现有资料
      console.warn('[user] fetchProfile failed', e)
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
  }

  // 应用启动时若已有 token，异步刷新画像
  function init() {
    if (token.value) fetchProfile()
  }

  watch(
    [token, user],
    () => {
      const data: PersistShape = { token: token.value, user: user.value }
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
      } catch {
        /* ignore */
      }
    },
    { deep: true }
  )

  return { token, user, loading, error, isLoggedIn, login, register, logout, fetchProfile, init }
})
