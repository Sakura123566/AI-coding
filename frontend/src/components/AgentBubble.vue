<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useKpStore } from '@/stores/knowledgeParty'
import EmotionAvatar from '@/components/emotion/EmotionAvatar.vue'

// 智能体浮标：右侧可拖动的（长）椭圆，会冒小话暗示自己是智能体；
// 点击弹出【小对话窗】（非模态浮层，不遮挡页面，可拖拽），具体对话能力由后端后续接入。
const pos = ref({ x: 0, y: 0 })
const dragging = ref(false)
const moved = ref(false)
const chatOpen = ref(false)
const chatPos = ref({ x: 0, y: 0 })

const hints = [
  '我是研究小助手，有疑问戳我～',
  '点我一下，咱们聊聊这篇文献',
  '需要我帮你梳理方向吗？',
  '我是智能体，随时待命帮你导航',
  '卡住了？问我准没错 😉'
]
const hintIdx = ref(0)
let hintTimer: ReturnType<typeof setInterval> | null = null

const CHAT_W = 330
const CHAT_H = 460

// 情绪头像：用 store 的稳定会话 id（可经 URL ?emotionSession= 覆盖，便于后端联调）
const store = useKpStore()
const emotionSessionId = computed(() => {
  const params = new URLSearchParams(window.location.search)
  return params.get('emotionSession') || store.emotionSessionId
})

onMounted(() => {
  // 默认位置：右边中上部
  pos.value = { x: window.innerWidth - 96, y: Math.round(window.innerHeight * 0.3) }
  hintTimer = setInterval(() => {
    hintIdx.value = (hintIdx.value + 1) % hints.length
  }, 4200)
})
onBeforeUnmount(() => {
  if (hintTimer) clearInterval(hintTimer)
})

let start = { x: 0, y: 0, px: 0, py: 0 }
function onDown(e: MouseEvent) {
  dragging.value = true
  moved.value = false
  start = { x: e.clientX, y: e.clientY, px: pos.value.x, py: pos.value.y }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  document.body.style.userSelect = 'none'
}
function onMove(e: MouseEvent) {
  if (!dragging.value) return
  const dx = e.clientX - start.x
  const dy = e.clientY - start.y
  if (Math.abs(dx) > 3 || Math.abs(dy) > 3) moved.value = true
  pos.value = {
    x: Math.max(8, Math.min(window.innerWidth - 80, start.px + dx)),
    y: Math.max(8, Math.min(window.innerHeight - 130, start.py + dy))
  }
}
function onUp() {
  dragging.value = false
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
  document.body.style.userSelect = ''
}
function onClick() {
  // 拖动过则不视为点击
  if (moved.value) return
  chatOpen.value = !chatOpen.value
  if (chatOpen.value) {
    // 小窗默认出现在浮标左侧，避免超出视口
    chatPos.value = {
      x: Math.max(8, Math.min(window.innerWidth - CHAT_W - 8, pos.value.x - CHAT_W - 16)),
      y: Math.max(8, Math.min(window.innerHeight - CHAT_H - 8, pos.value.y - 40))
    }
  }
}

// —— 小对话窗拖拽（按标题栏拖动）——
let cstart = { x: 0, y: 0, px: 0, py: 0 }
function onChatDown(e: MouseEvent) {
  cstart = { x: e.clientX, y: e.clientY, px: chatPos.value.x, py: chatPos.value.y }
  window.addEventListener('mousemove', onChatMove)
  window.addEventListener('mouseup', onChatUp)
  document.body.style.userSelect = 'none'
}
function onChatMove(e: MouseEvent) {
  const dx = e.clientX - cstart.x
  const dy = e.clientY - cstart.y
  chatPos.value = {
    x: Math.max(8, Math.min(window.innerWidth - CHAT_W - 8, cstart.px + dx)),
    y: Math.max(8, Math.min(window.innerHeight - CHAT_H - 8, cstart.py + dy))
  }
}
function onChatUp() {
  window.removeEventListener('mousemove', onChatMove)
  window.removeEventListener('mouseup', onChatUp)
  document.body.style.userSelect = ''
}

// —— 对话（占位，后端后续接入真实智能体）——
interface Msg {
  role: 'user' | 'agent'
  text: string
}
const messages = ref<Msg[]>([
  { role: 'agent', text: '嗨，我是知识派对的研究智能体～有想深挖的方向随时叫我。' }
])
const input = ref('')
function send() {
  const t = input.value.trim()
  if (!t) return
  messages.value.push({ role: 'user', text: t })
  input.value = ''
  // 后端接入前的占位回复：先记下用户问题，具体对话能力由后端实现
  messages.value.push({
    role: 'agent',
    text: '（智能体对话能力将由后端接入，敬请期待～我先把你的问题记下了）'
  })
}
</script>

<template>
  <div
    class="agent-float"
    :class="{ dragging }"
    :style="{ left: pos.x + 'px', top: pos.y + 'px' }"
  >
    <!-- 小话气泡：暗示自己是智能体 -->
    <div class="agent-hint">{{ hints[hintIdx] }}</div>
    <!-- 长椭圆浮标 -->
    <div
      class="agent-bubble"
      title="我是研究智能体，戳我聊天"
      @mousedown="onDown"
      @click="onClick"
    >
      <span class="agent-emoji">🤖</span>
    </div>
  </div>

  <!-- 小对话窗：非模态浮层，不遮挡页面，可拖拽 -->
  <div
    v-if="chatOpen"
    class="agent-chat"
    :style="{ left: chatPos.x + 'px', top: chatPos.y + 'px', width: CHAT_W + 'px' }"
  >
    <div class="agent-chat-head" @mousedown="onChatDown">
      <span class="agent-chat-title">🤖 研究智能体</span>
      <button class="agent-chat-close" title="收起" @click="chatOpen = false">×</button>
    </div>
    <!-- 情绪头像：默认订阅 store 稳定会话，后端经 SSE 推送情绪状态 -->
    <div class="agent-emotion">
      <EmotionAvatar :session-id="emotionSessionId" :size="120" />
    </div>
    <div class="chat">
      <div
        v-for="(m, i) in messages"
        :key="i"
        class="chat-row"
        :class="m.role"
      >
        <div class="chat-avatar">{{ m.role === 'agent' ? '🤖' : '🧑' }}</div>
        <div class="chat-bubble">{{ m.text }}</div>
      </div>
    </div>
    <div class="chat-input">
      <el-input
        v-model="input"
        placeholder="和智能体说点什么…（对话能力后端接入中）"
        @keydown.enter="send"
      />
      <el-button type="primary" @click="send">发送</el-button>
    </div>
  </div>
</template>

<style scoped>
.agent-float {
  position: fixed;
  z-index: 55;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: grab;
}
.agent-float.dragging {
  cursor: grabbing;
}
/* 长椭圆（竖向）浮标 */
.agent-bubble {
  width: 56px;
  height: 92px;
  border-radius: 50%;
  background: linear-gradient(160deg, #6a5cff 0%, #2b6cff 100%);
  box-shadow: 0 8px 22px rgba(43, 108, 255, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  animation: agent-pulse 2.4s ease-in-out infinite;
  user-select: none;
}
.agent-emoji {
  font-size: 26px;
}
@keyframes agent-pulse {
  0%,
  100% {
    transform: scale(1);
    box-shadow: 0 8px 22px rgba(43, 108, 255, 0.35);
  }
  50% {
    transform: scale(1.06);
    box-shadow: 0 10px 28px rgba(43, 108, 255, 0.5);
  }
}
/* 小话气泡 */
.agent-hint {
  max-width: 180px;
  margin-bottom: 10px;
  padding: 7px 11px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #e3e6eb;
  color: #5a6b8c;
  font-size: 12px;
  line-height: 1.5;
  text-align: center;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  position: relative;
}
.agent-hint::after {
  content: '';
  position: absolute;
  bottom: -6px;
  left: 50%;
  transform: translateX(-50%);
  border: 6px solid transparent;
  border-top-color: #fff;
  border-bottom: 0;
}

/* 小对话窗（非模态浮层） */
.agent-chat {
  position: fixed;
  z-index: 56;
  height: 460px;
  max-height: calc(100vh - 24px);
  background: #fff;
  border: 1px solid #e3e6eb;
  border-radius: 14px;
  box-shadow: 0 12px 36px rgba(20, 30, 60, 0.22);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.agent-chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: linear-gradient(160deg, #6a5cff 0%, #2b6cff 100%);
  color: #fff;
  cursor: move;
  flex: 0 0 auto;
}
.agent-chat-title {
  font-size: 14px;
  font-weight: 600;
}
.agent-chat-close {
  border: none;
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
}
.agent-chat-close:hover {
  background: rgba(255, 255, 255, 0.35);
}
/* 情绪头像区：头部下方、对话区上方，居中展示后端实时情绪 */
.agent-emotion {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px 10px 4px;
  background: linear-gradient(180deg, #f6f8ff 0%, #ffffff 100%);
  border-bottom: 1px solid #eef0f2;
  flex: 0 0 auto;
}
.chat {
  flex: 1 1 auto;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px 10px;
}
.chat-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.chat-row.user {
  flex-direction: row-reverse;
}
.chat-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: #eef3ff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex: 0 0 auto;
}
.chat-bubble {
  max-width: 230px;
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.6;
  background: #f2f4f8;
  color: #333;
  word-break: break-word;
}
.chat-row.user .chat-bubble {
  background: var(--el-color-primary);
  color: #fff;
}
.chat-input {
  display: flex;
  gap: 8px;
  padding: 10px;
  border-top: 1px solid #eef0f2;
  flex: 0 0 auto;
}
</style>
