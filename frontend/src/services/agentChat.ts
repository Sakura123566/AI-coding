// 智能体对话服务层（多轮对话 + 会话上下文）。
// 前端本地优先：默认走 mock（VITE_USE_MOCK 未显式置 'false' 即为 mock），
// 用规则式回复演示「多轮上下文 + 长期记忆（知道你是谁、记得上一轮）」；
// 后端就绪后切 VITE_USE_MOCK=false，POST /api/agent/chat 即可（契约见下）。
//
// 约定端点（真实后端）：
//   POST /api/agent/chat
//     body: { session_id, history:[{role,text}], settings:AgentSettings,
//             address_name:string, user_name:string, identity:string|null }
//     -> { reply: string }

import type { AgentSettings } from '../types/user'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'true') === 'true'

export interface ChatMessage {
  role: 'user' | 'agent'
  text: string
}

export interface SendContext {
  history: ChatMessage[] // 完整历史（含本次用户消息），用于多轮上下文
  settings: AgentSettings | null
  addressName: string // 希望被如何称呼（缺省回退 display_name）
  userName: string // 登录昵称 display_name
  identity: string | null // 身份资料
}

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

// —— mock 规则式回复：体现多轮上下文 + 身份联动 + 性格/语气 ——
function mockReply(ctx: SendContext): string {
  const name = ctx.addressName || ctx.userName || '朋友'
  const s = ctx.settings
  const personality = s?.personality ?? 'rigorous_warm'
  const custom = (s?.custom_instructions ?? '').trim()

  const userTurns = ctx.history.filter((m) => m.role === 'user')
  const lastUser = userTurns[userTurns.length - 1]?.text ?? ''
  const prevUser = userTurns.length > 1 ? userTurns[userTurns.length - 2].text : ''
  const identityTag = ctx.identity ? `（看你的身份是「${ctx.identity}」，` : '（'

  const greet = `你好，${name}${identityTag}咱们继续聊方向～）`

  let body = ''
  if (prevUser) {
    const p = prevUser.length > 16 ? prevUser.slice(0, 16) + '…' : prevUser
    body += `咱们接着刚才的话题——你之前提到「${p}」，`
  }
  const topic = lastUser.length > 24 ? lastUser.slice(0, 24) + '…' : lastUser
  body += `关于「${topic}」，`

  switch (personality) {
    case 'strict_reviewer':
      body += '我先从评审视角帮你厘清定义与边界，再给证据：建议先锁定 2–3 篇核心文献，沿「方法→证据→局限」读下去。'
      break
    case 'creative_companion':
      body += '咱们换个比喻来打开思路：把它想成搭积木，先有骨架再补细节；要不要我列几个可切入的子问题？'
      break
    case 'concise_socratic':
      body += '我想先反问你一个问题来收敛方向：你最想用它解决的具体场景是什么？'
      break
    case 'rigorous_warm':
    default:
      body += '我先用清晰的结构帮你拆解，再给可操作的下一步：先按「背景→核心工作→可迁移点」梳理，需要的话我再展开。'
      break
  }
  if (custom) {
    const c = custom.length > 40 ? custom.slice(0, 40) + '…' : custom
    body += `（已参考你的自定义指令：${c}）`
  }
  return `${greet} ${body}`
}

// —— 发送一条消息，返回智能体回复文本 ——
export async function sendAgentMessage(ctx: SendContext): Promise<string> {
  if (USE_MOCK) {
    await delay(700)
    return mockReply(ctx)
  }
  const res = await fetch(`${API_BASE}/api/agent/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      history: ctx.history,
      settings: ctx.settings,
      address_name: ctx.addressName,
      user_name: ctx.userName,
      identity: ctx.identity
    })
  })
  const data = await res.json().catch(() => ({}))
  if (data?.status === 'error' || (!res.ok && data?.status !== 'success')) {
    throw new Error(data?.message || `对话请求失败（HTTP ${res.status}）`)
  }
  return String(data?.reply ?? data?.text ?? '（智能体没有返回内容）')
}
