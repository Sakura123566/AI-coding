// 知识派对全局状态：空间(Spaces)、模式(搜索/收藏/历史)、收藏夹、标签、观看记录、检索结果
// 持久化到 localStorage，实现「按空间隔离检索记录 / 收藏分组」的能力。
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { fetchResearch, DEFAULT_LIMIT, ResearchApiError, type Paper, type ResearchReport } from '../services/research'

export interface Space {
  id: string
  name: string
  history: HistoryEntry[]
  favorites: Record<string, Paper> // 该收藏夹内的论文（按 paper.id 分组）
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
  paperTags: Record<string, string[]> // 全局自定义标签（跨收藏夹共享），按 paper.id
  viewed: Record<string, ViewedEntry>
  mode: KpMode
  autoSortByTopic: boolean // 星标时是否按当前主题自动归入/创建主题收藏夹
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

// 全局标签：按 paper.id 存 string[]，去空、去重
function normalizeTags(raw: any): Record<string, string[]> {
  if (!raw || typeof raw !== 'object') return {}
  const out: Record<string, string[]> = {}
  for (const [k, v] of Object.entries(raw)) {
    if (Array.isArray(v)) {
      const arr = Array.from(
        new Set(v.map((t: any) => String(t).trim()).filter((t: string) => t.length > 0))
      )
      if (arr.length) out[String(k)] = arr
    }
  }
  return out
}

function loadState(): PersistShape | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    const legacyFavs = normalizeFavorites(data?.favorites) // 旧版：全局扁平收藏
    const spaces: Space[] = Array.isArray(data?.spaces)
      ? data.spaces.map((s: any) => ({
          id: String(s?.id ?? newId()),
          name: String(s?.name ?? '默认空间'),
          history: normalizeHistory(s?.history),
          favorites: normalizeFavorites(s?.favorites)
        }))
      : [{ id: newId(), name: '默认空间', history: [], favorites: legacyFavs }]
    // 旧版迁移：若历史数据里存在顶层 favorites（无 spaces），已在上一项处理；
    // 若有 spaces 同时也有顶层 favorites（过渡态），并入第一个空间（不覆盖已有键）。
    if (Array.isArray(data?.spaces) && Object.keys(legacyFavs).length) {
      const f = spaces[0].favorites
      for (const [k, v] of Object.entries(legacyFavs)) {
        if (!f[k]) f[k] = v as Paper
      }
    }
    return {
      spaces,
      currentSpaceId: String(data?.currentSpaceId ?? spaces[0].id),
      paperTags: normalizeTags(data?.paperTags),
      viewed: normalizeViewed(data?.viewed),
      // 模式需在校验集合内，否则回退 'search'（'graph' 为有效模式，保留）
      mode: (['search', 'favorites', 'history', 'graph'].includes(data?.mode)
        ? (data?.mode as KpMode)
        : 'search') ?? 'search',
      // 按主题自动归类：旧数据缺省也默认开启（用户要求初始打开）
      autoSortByTopic: typeof data?.autoSortByTopic === 'boolean' ? data.autoSortByTopic : true
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
    saved?.spaces?.length ? saved.spaces : [{ id: newId(), name: '默认空间', history: [], favorites: {} }]
  )
  const currentSpaceId = ref<string>(saved?.currentSpaceId ?? spaces.value[0].id)
  const paperTags = ref<Record<string, string[]>>(saved?.paperTags ?? {}) // 全局自定义标签
  const viewed = ref<Record<string, ViewedEntry>>(saved?.viewed ?? {})
  const mode = ref<KpMode>(saved?.mode ?? 'search')
  // 星标时按当前主题自动归入/创建主题收藏夹（收藏详情页可开关，默认开启）
  const autoSortByTopic = ref<boolean>(saved?.autoSortByTopic ?? true)

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
  // 当前收藏夹的论文列表（切换空间即切换收藏夹）
  const favoriteList = computed(() => Object.values(currentSpace.value.favorites))
  const viewedList = computed(() => Object.values(viewed.value))
  // 全局标签汇总（跨收藏夹共享，去重排序），用于收藏页筛选条
  const allTags = computed(() => {
    const set = new Set<string>()
    for (const arr of Object.values(paperTags.value)) for (const t of arr) set.add(t)
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'zh'))
  })

  function setMode(m: KpMode) {
    mode.value = m
  }

  function switchSpace(id: string) {
    if (spaces.value.some((s) => s.id === id)) currentSpaceId.value = id
  }

  function addSpace(name: string) {
    const sp: Space = { id: newId(), name, history: [], favorites: {} }
    spaces.value.push(sp)
    currentSpaceId.value = sp.id
  }

  // 按名称查找收藏夹（精确匹配）；不存在则创建，**但不切换**当前收藏夹
  function ensureSpaceByName(name: string): string {
    const n = name.trim()
    const existing = spaces.value.find((s) => s.name === n)
    if (existing) return existing.id
    const sp: Space = { id: newId(), name: n, history: [], favorites: {} }
    spaces.value.push(sp)
    return sp.id
  }

  function setAutoSortByTopic(v: boolean) {
    autoSortByTopic.value = v
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

  // —— 收藏（按当前空间/收藏夹分组）——
  function isFavorite(id: string): boolean {
    return !!currentSpace.value.favorites[id]
  }

  // 收藏/取消收藏：作用于「当前空间」这个收藏夹
  function toggleFavorite(paper: Paper) {
    const sp = currentSpace.value
    const f = { ...sp.favorites }
    if (f[paper.id]) {
      delete f[paper.id]
    } else {
      f[paper.id] = { ...paper }
    }
    sp.favorites = f
  }

  // 是否收藏在「任意」收藏夹里（用于论文卡片星标态，跨空间）
  function isFavInAny(id: string): boolean {
    return spaces.value.some((s) => s.favorites[id])
  }

  // 列出包含该论文的所有收藏夹 id（用于弹窗里展示勾选态）
  function favoriteSpaceIdsOf(id: string): string[] {
    return spaces.value.filter((s) => s.favorites[id]).map((s) => s.id)
  }

  // 把论文加入指定收藏夹（不覆盖其它收藏夹里的同篇）
  function addToSpace(spaceId: string, paper: Paper) {
    const sp = spaces.value.find((s) => s.id === spaceId)
    if (!sp) return
    sp.favorites = { ...sp.favorites, [paper.id]: { ...paper } }
  }

  // 从指定收藏夹移除该论文
  function removeFromSpace(spaceId: string, paperId: string) {
    const sp = spaces.value.find((s) => s.id === spaceId)
    if (!sp) return
    const f = { ...sp.favorites }
    delete f[paperId]
    sp.favorites = f
  }

  // 取消该论文在「所有」收藏夹里的收藏
  function cancelAllFavorites(paperId: string) {
    for (const s of spaces.value) {
      if (s.favorites[paperId]) {
        const f = { ...s.favorites }
        delete f[paperId]
        s.favorites = f
      }
    }
  }

  // 清空「当前空间」这个收藏夹
  function clearFavorites() {
    currentSpace.value.favorites = {}
  }

  function clearViewed() {
    viewed.value = {}
  }

  // —— 全局自定义标签（跨收藏夹共享）——
  function tagsOf(id: string): string[] {
    return paperTags.value[id] ?? []
  }
  function addTag(id: string, rawTag: string) {
    const tag = rawTag.trim()
    if (!tag) return
    const cur = paperTags.value[id] ?? []
    if (cur.includes(tag)) return
    paperTags.value = { ...paperTags.value, [id]: [...cur, tag] }
  }
  function removeTag(id: string, tag: string) {
    const cur = paperTags.value[id]
    if (!cur) return
    const next = cur.filter((t) => t !== tag)
    const map = { ...paperTags.value }
    if (next.length) map[id] = next
    else delete map[id]
    paperTags.value = map
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
    [spaces, currentSpaceId, paperTags, viewed, mode, autoSortByTopic],
    () => {
      const data: PersistShape = {
        spaces: spaces.value,
        currentSpaceId: currentSpaceId.value,
        paperTags: paperTags.value,
        viewed: viewed.value,
        mode: mode.value,
        autoSortByTopic: autoSortByTopic.value
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
    paperTags,
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
    allTags,
    autoSortByTopic,
    setMode,
    switchSpace,
    addSpace,
    ensureSpaceByName,
    setAutoSortByTopic,
    removeSpace,
    recordSearch,
    markViewed,
    isFavorite,
    toggleFavorite,
    isFavInAny,
    favoriteSpaceIdsOf,
    addToSpace,
    removeFromSpace,
    cancelAllFavorites,
    clearFavorites,
    clearViewed,
    tagsOf,
    addTag,
    removeTag,
    doSearch,
    retry
  }
})
