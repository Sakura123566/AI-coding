import { apiBase, isDemoMode } from '../config/runtime'
// 智能体对话服务层（多轮对话 + 会话上下文）。
// 默认使用 demo 数据（VITE_APP_MODE=demo），
// 用规则式回复演示「多轮上下文 + 长期记忆（知道你是谁、记得上一轮）」；
// 后端就绪后把 VITE_APP_MODE 设为 backend，即可对接真实会话接口（契约见下）。
//
// 约定端点（真实后端，backend/routers/chat_api.py，前缀 /api/chat，需 Bearer 登录）：
//   POST /api/chat/sessions            (Bearer, {title?}) -> ok(session={id,title,...})
//   POST /api/chat/message             (Bearer, {session_id, content}) -> ok(reply, emotion, intent, papers, ...)
//   GET  /api/chat/sessions            (Bearer) -> ok(sessions, count)
//   DELETE /api/chat/sessions/{id}     (Bearer) -> ok(deleted)
//   POST /api/chat/sessions/{id}/close (Bearer) -> ok(...)  // 触发长期记忆抽取
//
// 说明：真实后端自己维护多轮上下文（服务端按 session 存消息），前端只需传最新一条
//       content + session_id，返回 reply（以及可选 emotion / papers 供 UI 展示）。
//       前端仍本地保存一份消息用于展示与历史，做到「刷新不丢对话」。

import type { AgentSettings } from '../types/user'

const API_BASE = apiBase
const USE_MOCK = isDemoMode

export interface ChatMessage {
  role: 'user' | 'agent'
  text: string
  emotion?: string
  papers?: any[]
}

export interface SendContext {
  token: string | null // 真实后端需要登录态（Bearer）
  backendSessionId: string | null // 真实后端会话号（首次发送时惰性创建）
  content: string // 本次用户消息
  settings: AgentSettings | null
  addressName: string // 希望被如何称呼（缺省回退 display_name）
  userName: string // 登录昵称 display_name
  identity: string | null // 身份资料
  history: ChatMessage[] // 仅 mock 规则回复用，真实后端由服务端维护上下文
}

// 真实后端返回的结构（ok(...) 包裹，取 reply 等字段）
export interface ChatResult {
  reply: string
  emotion?: string
  intent?: string
  papers?: any[]
  mode?: string
  degraded?: boolean
  backendSessionId?: string | null
}

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

const RESEARCH_INTENT_RE = /(论文|文献|检索|找几篇|找一些|最新进展|研究现状|survey|paper|papers|arxiv)/i

function isResearchRequest(text: string): boolean {
  return RESEARCH_INTENT_RE.test(text || '')
}

function extractResearchTopic(text: string): string {
  const cleaned = String(text || '')
    .replace(/帮我|请|麻烦|能不能|可以|给我|一下|看看|找一些|找几篇|找找|找|查查|搜搜|搜索|检索|相关|论文|文献|最新进展|研究现状|survey|papers?|arxiv/gi, ' ')
    .replace(/[，。！？?!,.;；:：]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return cleaned || String(text || '').trim()
}

async function mockResearchResult(ctx: SendContext): Promise<ChatResult> {
  const topic = extractResearchTopic(ctx.content)
  const { mockResearchForTopic } = await import('../mocks/research.mock')
  const result = mockResearchForTopic(topic, 5)
  if (!result.papers.length) {
    return {
      reply: `当前演示数据中没有找到与「${topic}」匹配的论文。可以试试 GNN、图神经网络、知识图谱、RAG 或推荐系统。`,
      emotion: 'confused',
      intent: 'research',
      mode: 'demo',
      backendSessionId: ctx.backendSessionId
    }
  }
  const lines = result.papers.map((paper) => {
    const year = paper.year ? `${paper.year} 年` : '年份未知'
    return `[${paper.id}] ${paper.title}（${year}）`
  })
  return {
    reply: `当前为演示检索结果，围绕「${topic}」找到 ${result.papers.length} 篇论文：\n\n${lines.join('\n')}\n\n这些题目来自内置样例，未访问真实论文源。`,
    emotion: 'excited',
    intent: 'research',
    papers: result.papers,
    mode: 'demo',
    backendSessionId: ctx.backendSessionId
  }
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

// —— 真实后端：创建会话，返回 session id ——
export async function createChatSession(token: string, title?: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/chat/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(title ? { title } : {})
  })
  const data = await parseJson(res)
  const id = data?.session?.id ?? data?.id
  if (!id) throw new Error('创建会话失败：后端未返回会话 ID')
  return String(id)
}

// —— 真实后端：删除会话（best-effort，失败不阻塞 UI）——
export async function deleteChatSession(token: string, backendSessionId: string): Promise<void> {
  await fetch(`${API_BASE}/api/chat/sessions/${backendSessionId}`, {
    method: 'DELETE',
    headers: authHeaders(token)
  }).catch(() => {})
}

// —— 真实后端：发送一条消息，返回完整结果 ——
async function sendChatMessage(token: string, sessionId: string, content: string): Promise<any> {
  const res = await fetch(`${API_BASE}/api/chat/message`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ session_id: sessionId, content })
  })
  return parseJson(res)
}

// —— 发送一条消息，返回智能体回复文本 + 元数据 ——
export async function sendAgentMessage(ctx: SendContext): Promise<ChatResult> {
  if (USE_MOCK) {
    await delay(700)
    if (isResearchRequest(ctx.content)) return await mockResearchResult(ctx)
    return {
      reply: mockReply(ctx),
      emotion: 'happy',
      mode: 'demo',
      backendSessionId: ctx.backendSessionId
    }
  }
  if (!ctx.token) {
    throw new Error('请先登录后再与智能体对话（真实后端需要账号）')
  }
  // 真实后端要求先建会话；用首条用户消息作为标题，惰性创建一次。
  let sid = ctx.backendSessionId
  if (!sid) {
    sid = await createChatSession(ctx.token, ctx.content.slice(0, 20))
  }
  const data = await sendChatMessage(ctx.token, sid, ctx.content)
  return {
    reply: String(data?.reply ?? '（智能体没有返回内容）'),
    emotion: data?.emotion,
    intent: data?.intent,
    papers: data?.papers,
    mode: data?.mode,
    degraded: data?.degraded,
    backendSessionId: sid
  }
}
