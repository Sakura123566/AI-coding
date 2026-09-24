// 智能体对话状态：多轮会话 + 历史，本地优先持久化到 localStorage（长期记忆）。
// 与 user.ts / knowledgeParty.ts 同样的持久化写法，刷新不丢对话历史。
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { sendAgentMessage, deleteChatSession, type ChatMessage } from '../services/agentChat'
import { useUserStore } from './user'
import { useAgentSettings } from '../composables/useAgentSettings'

const STORAGE_KEY = 'kp-agent-chat-v1'

interface ChatSession {
  id: string
  title: string
  messages: ChatMessage[]
  updatedAt: number
  // 真实后端会话号（mock 模式恒为 null；切真实后端后首次发送时惰性创建并回填）
  backendSessionId?: string | null
}
interface PersistShape {
  sessions: ChatSession[]
  currentId: string | null
}

function loadState(): PersistShape | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const d = JSON.parse(raw)
    return { sessions: d.sessions ?? [], currentId: d.currentId ?? null }
  } catch {
    return null
  }
}

function genId(): string {
  return 'cs-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
}

function greeting(text: string): ChatMessage {
  return { role: 'agent', text }
}

export const useAgentChatStore = defineStore('agentChat', () => {
  const saved = loadState()
  const sessions = ref<ChatSession[]>(saved?.sessions ?? [])
  const currentId = ref<string | null>(saved?.currentId ?? null)
  const loading = ref(false)

  const current = computed(() => sessions.value.find((s) => s.id === currentId.value) || null)
  const messages = computed<ChatMessage[]>(() => current.value?.messages ?? [])

  function ensureSession(): ChatSession {
    let s = current.value
    if (!s) {
      s = {
        id: genId(),
        title: '新对话',
        messages: [greeting('嗨，我是知识派对的研究智能体～有想深挖的方向随时叫我。')],
        updatedAt: Date.now()
      }
      sessions.value.unshift(s)
      currentId.value = s.id
    }
    return s
  }

  function newSession() {
    const cur = current.value
    // 当前会话还没聊过（只有开场白），直接复用，避免堆积空会话
    if (cur && cur.messages.length <= 1 && cur.title === '新对话') {
      cur.messages = [greeting('嗨，我是知识派对的研究智能体～开个新话题吧！')]
      cur.updatedAt = Date.now()
      return
    }
    const s: ChatSession = {
      id: genId(),
      title: '新对话',
      messages: [greeting('嗨，我是知识派对的研究智能体～开个新话题吧！')],
      updatedAt: Date.now()
    }
    sessions.value.unshift(s)
    currentId.value = s.id
  }

  function selectSession(id: string) {
    currentId.value = id
  }

  function deleteSession(id: string) {
    const target = sessions.value.find((s) => s.id === id)
    // 真实后端：会话号存在时一并删除（best-effort，失败不阻塞 UI）
    if (target?.backendSessionId) {
      const userStore = useUserStore()
      if (userStore.token) {
        deleteChatSession(userStore.token, target.backendSessionId).catch(() => {})
      }
    }
    sessions.value = sessions.value.filter((s) => s.id !== id)
    if (currentId.value === id) {
      currentId.value = sessions.value[0]?.id ?? null
    }
    if (!currentId.value) ensureSession()
  }

  async function send(text: string) {
    const s = ensureSession()
    s.messages.push({ role: 'user', text })
    s.updatedAt = Date.now()
    loading.value = true
    try {
      const userStore = useUserStore()
      const agent = useAgentSettings()
      const settings = agent.state.settings
      const addressName =
        (settings?.agent_address_name && settings.agent_address_name.trim()) ||
        userStore.user?.display_name ||
        ''
      const res = await sendAgentMessage({
        token: userStore.token || null,
        backendSessionId: s.backendSessionId ?? null,
        content: text,
        settings,
        addressName,
        userName: userStore.user?.display_name || '',
        identity: userStore.user?.identity || null,
        history: s.messages
      })
      s.messages.push({ role: 'agent', text: res.reply, emotion: res.emotion, papers: res.papers })
      // 回填真实后端会话号，后续消息复用同一会话（多轮上下文）
      if (res.backendSessionId) s.backendSessionId = res.backendSessionId
      // 用首条用户消息生成会话标题
      const firstUser = s.messages.find((m) => m.role === 'user')
      if (firstUser && s.title === '新对话') {
        s.title = firstUser.text.length > 20 ? firstUser.text.slice(0, 20) + '…' : firstUser.text
      }
      s.updatedAt = Date.now()
    } catch (e) {
      s.messages.push({
        role: 'agent',
        text: '（对话出错了，请稍后再试）' + (e instanceof Error ? `：${e.message}` : '')
      })
    } finally {
      loading.value = false
    }
  }

  // 持久化：刷新不丢会话历史（长期记忆）
  watch(
    [sessions, currentId],
    () => {
      const data: PersistShape = { sessions: sessions.value, currentId: currentId.value }
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
      } catch {
        /* ignore */
      }
    },
    { deep: true }
  )

  return {
    sessions,
    currentId,
    loading,
    current,
    messages,
    ensureSession,
    newSession,
    selectSession,
    deleteSession,
    send
  }
})
