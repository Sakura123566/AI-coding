// 知识派对全局状态：空间(Spaces)、模式(搜索/收藏/历史)、收藏夹、观看记录、检索结果
// 持久化到 localStorage，实现「按空间隔离检索记录」的能力。
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { fetchResearch, DEFAULT_LIMIT, ResearchApiError, type Paper, type ResearchReport } from '../services/research'

export interface Space {
  id: string
  name: string
  history: HistoryEntry[]
}

// 搜索记录条目：查询词 + 时间戳（用于历史页展示「多久前」）
export interface HistoryEntry {
  q: string
  at: number
}

// 观看过的文献：Paper 附带浏览时间戳
export interface ViewedEntry extends Paper {
  at: number
}

export type KpMode = 'search' | 'favorites' | 'history' | 'graph'

const STORAGE_KEY = 'kp-store-v1'

interface PersistShape {
  spaces: Space[]
  currentSpaceId: string
  favorites: Record<string, Paper>
  viewed: Record<string, ViewedEntry>
  mode: KpMode
}

// 兼容旧版 localStorage：历史曾是 string[]，观看记录无 at 字段
function normalizeHistory(raw: any): HistoryEntry[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map((h: any) =>
      typeof h === 'string'
        ? { q: h, at: 0 }
        : h && typeof h.q === 'string'
          ? { q: h.q, at: Number(h.at) || 0 }
          : null
    )
    .filter((x: any): x is HistoryEntry => x !== null)
    .slice(0, 20)
}

function normalizeViewed(raw: any): Record<string, ViewedEntry> {
  if (!raw || typeof raw !== 'object') return {}
  const out: Record<string, ViewedEntry> = {}
  for (const [k, v] of Object.entries(raw)) {
    const p = v as any
    if (p && typeof p.title === 'string') {
      // 以 paper.id 作为键（url 可能为空，不能作为唯一键）
      out[String(p.id ?? k)] = { ...(p as Paper), at: Number(p.at) || 0 }
    }
  }
  return out
}

// 收藏同样以 paper.id 为键（兼容旧版以 url 为键的本地数据）
function normalizeFavorites(raw: any): Record<string, Paper> {
  if (!raw || typeof raw !== 'object') return {}
  const out: Record<string, Paper> = {}
  for (const [k, v] of Object.entries(raw)) {
    const p = v as any
    if (p && typeof p.title === 'string') {
      out[String(p.id ?? k)] = { ...(p as Paper) }
    }
  }
  return out
}

function loadState(): PersistShape | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    const spaces: Space[] = Array.isArray(data?.spaces)
      ? data.spaces.map((s: any) => ({
          id: String(s?.id ?? newId()),
          name: String(s?.name ?? '默认空间'),
          history: normalizeHistory(s?.history)
        }))
      : [{ id: newId(), name: '默认空间', history: [] }]
    return {
      spaces,
      currentSpaceId: String(data?.currentSpaceId ?? spaces[0].id),
      favorites: normalizeFavorites(data?.favorites),
      viewed: normalizeViewed(data?.viewed),
      // 模式需在校验集合内，否则回退 'search'（'graph' 为有效模式，保留）
      mode: (['search', 'favorites', 'history', 'graph'].includes(data?.mode)
        ? (data?.mode as KpMode)
        : 'search') ?? 'search'
    }
  } catch {
    return null
  }
}

function newId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : 'sp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7)
}

// 情绪模块联调用：每个浏览器一个稳定会话 id（持久化），后端据此推送情绪事件。
// 后端队友联调时也可用 URL ?emotionSession= 直接覆盖。
const EMOTION_SESSION_KEY = 'kp-emotion-session-id'
function loadOrCreateEmotionSessionId(): string {
  try {
    const existing = localStorage.getItem(EMOTION_SESSION_KEY)
    if (existing) return existing
  } catch {
    /* ignore */
  }
  const id = newId()
  try {
    localStorage.setItem(EMOTION_SESSION_KEY, id)
  } catch {
    /* ignore */
  }
  return id
}

export const useKpStore = defineStore('knowledgeParty', () => {
  const saved = loadState()

  const spaces = ref<Space[]>(
    saved?.spaces?.length ? saved.spaces : [{ id: newId(), name: '默认空间', history: [] }]
  )
  const currentSpaceId = ref<string>(saved?.currentSpaceId ?? spaces.value[0].id)
  const favorites = ref<Record<string, Paper>>(saved?.favorites ?? {})
  const viewed = ref<Record<string, ViewedEntry>>(saved?.viewed ?? {})
  const mode = ref<KpMode>(saved?.mode ?? 'search')

  // 检索结果（全应用共享，App / HistoryView 等均通过 store 读取同一份）
  const topic = ref('')
  const loading = ref(false)
  // 情绪模块联调会话 id（稳定、持久化）
  const emotionSessionId = ref<string>(loadOrCreateEmotionSessionId())
  // 加载状态机：'searching'（正在检索论文…）→ 'analyzing'（已找到，正在生成报告…）→ 终态由 loading 收尾
  const phase = ref<'idle' | 'searching' | 'analyzing'>('idle')
  const error = ref('')
  // 错误是否可重试：4xx（输入问题）为 false，5xx/网络/上游超时等为 true
  const retryableError = ref(false)
  const papers = ref<Paper[]>([])
  const report = ref<ResearchReport | null>(null)
  // 报告降级：论文有、报告没生成（report 为 null 但 report_error 有值）
  const reportError = ref<string | null>(null)
  // 后端告警（如「本地样例报告（LLM_PROVIDER=mock）」「中文主题已转为英文检索」）
  const warnings = ref<string[]>([])
  // 中文主题被后端转成的英文检索词
  const resolvedKeyword = ref<string | null>(null)
  // 后端 success 负载里的 message（空结果时作为空态文案）
  const backendMessage = ref<string | null>(null)
  // 是否已发起过搜索：用于区分「初始居中态」与「搜索后无结果（趣味空态）」
  const searched = ref(false)

  // 2.5s 后把「检索中」切到「分析中」的计时器（后端一次性返回，前端用计时模拟两阶段）
  let phaseTimer: ReturnType<typeof setTimeout> | null = null
  function clearPhaseTimer() {
    if (phaseTimer) {
      clearTimeout(phaseTimer)
      phaseTimer = null
    }
  }

  const currentSpace = computed(
    () => spaces.value.find((s) => s.id === currentSpaceId.value) ?? spaces.value[0]
  )
  const currentHistory = computed(() => currentSpace.value.history)
  const favoriteList = computed(() => Object.values(favorites.value))
  const viewedList = computed(() => Object.values(viewed.value))

  function setMode(m: KpMode) {
    mode.value = m
  }

  function switchSpace(id: string) {
    if (spaces.value.some((s) => s.id === id)) currentSpaceId.value = id
  }

  function addSpace(name: string) {
    const sp: Space = { id: newId(), name, history: [] }
    spaces.value.push(sp)
    currentSpaceId.value = sp.id
  }

  function removeSpace(id: string) {
    if (spaces.value.length <= 1) return
    const idx = spaces.value.findIndex((s) => s.id === id)
    if (idx === -1) return
    spaces.value.splice(idx, 1)
    if (currentSpaceId.value === id) currentSpaceId.value = spaces.value[0].id
  }

  // 记录一次搜索到「当前空间」：去重、最近优先、最多 20 条，并带时间戳
  function recordSearch(t: string) {
    const q = t.trim()
    if (!q) return
    const sp = currentSpace.value
    const entry: HistoryEntry = { q, at: Date.now() }
    sp.history = [entry, ...sp.history.filter((h) => h.q !== q)].slice(0, 20)
  }

  // 记录「点开观看过的文献」：按 paper.id 去重，并写入浏览时间戳
  function markViewed(paper: Paper) {
    viewed.value = { ...viewed.value, [paper.id]: { ...paper, at: Date.now() } }
  }

  function isFavorite(id: string): boolean {
    return !!favorites.value[id]
  }

  function toggleFavorite(paper: Paper) {
    if (favorites.value[paper.id]) {
      const next = { ...favorites.value }
      delete next[paper.id]
      favorites.value = next
    } else {
      favorites.value = { ...favorites.value, [paper.id]: paper }
    }
  }

  function clearFavorites() {
    favorites.value = {}
  }

  function clearViewed() {
    viewed.value = {}
  }

  async function doSearch(query?: string) {
    const t = (query ?? topic.value).trim()
    if (!t) {
      error.value = '请输入研究主题'
      searched.value = true
      return
    }
    topic.value = t
    recordSearch(t) // 写入当前空间历史
    searched.value = true
    loading.value = true
    error.value = ''
    retryableError.value = false
    papers.value = []
    report.value = null
    reportError.value = null
    warnings.value = []
    resolvedKeyword.value = null
    backendMessage.value = null
    phase.value = 'searching'
    clearPhaseTimer()
    // 2.5s 后从「检索中」切到「分析中」（后端一次性返回，前端用计时模拟两阶段）
    phaseTimer = setTimeout(() => {
      if (loading.value) phase.value = 'analyzing'
    }, 2500)
    try {
      const res = await fetchResearch(t, DEFAULT_LIMIT)
      papers.value = res.papers
      report.value = res.report
      reportError.value = res.reportError
      warnings.value = res.warnings
      resolvedKeyword.value = res.resolvedKeyword
      backendMessage.value = res.message
    } catch (e) {
      // 应用层错误已携带 error_code 与 retryable，直接透传可读文案
      if (e instanceof ResearchApiError) {
        error.value = e.message
        retryableError.value = e.retryable
      } else {
        error.value = e instanceof Error ? e.message : '未知错误'
        retryableError.value = false
      }
    } finally {
      clearPhaseTimer()
      loading.value = false
      phase.value = 'idle'
    }
  }

  // 重试：用当前输入框内容（即上一次查询）重新发起检索
  function retry() {
    doSearch(topic.value)
  }

  watch(
    [spaces, currentSpaceId, favorites, viewed, mode],
    () => {
      const data: PersistShape = {
        spaces: spaces.value,
        currentSpaceId: currentSpaceId.value,
        favorites: favorites.value,
        viewed: viewed.value,
        mode: mode.value
      }
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
      } catch {
        /* 忽略持久化失败（如隐私模式） */
      }
    },
    { deep: true }
  )

  return {
    spaces,
    currentSpaceId,
    favorites,
    viewed,
    mode,
    topic,
    loading,
    emotionSessionId,
    phase,
    error,
    retryableError,
    papers,
    report,
    reportError,
    warnings,
    resolvedKeyword,
    backendMessage,
    searched,
    currentSpace,
    currentHistory,
    favoriteList,
    viewedList,
    setMode,
    switchSpace,
    addSpace,
    removeSpace,
    recordSearch,
    markViewed,
    isFavorite,
    toggleFavorite,
    clearFavorites,
    clearViewed,
    doSearch,
    retry
  }
})
