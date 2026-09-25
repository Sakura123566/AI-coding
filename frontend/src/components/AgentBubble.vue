<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useKpStore } from '@/stores/knowledgeParty'
import { useAgentChatStore } from '@/stores/agentChat'
import EmotionAvatar from '@/components/emotion/EmotionAvatar.vue'
import { useSpeech } from '@/composables/useSpeech'
import { useAgentSettings } from '@/composables/useAgentSettings'

// 智能体入口：右下角紧凑启动按钮（不挡视线）；对话时聊天框标题头像带小动画。
// 具体对话能力由后端提供（多轮 + 历史本地持久化，见 stores/agentChat）。
const chatOpen = ref(false)
const chatPos = ref({ x: 0, y: 0 })

const CHAT_W = 330
const CHAT_H = 460

// 情绪头像：用 store 的稳定会话 id（可经 URL ?emotionSession= 覆盖，便于后端联调）
const store = useKpStore()
// 启动按钮图标：用情绪头像待机图（public/emojis/persona_idle.webp），与对话页头像一致
const launcherIcon = (import.meta.env.BASE_URL || '/') + 'emojis/persona_idle.webp'
const emotionSessionId = computed(() => {
  const params = new URLSearchParams(window.location.search)
  return params.get('emotionSession') || store.emotionSessionId
})

const chat = useAgentChatStore()

onMounted(() => {
  chat.ensureSession()
})

function openChat() {
  if (chatOpen.value) return
  chatOpen.value = true
  // 默认出现在右下角、启动按钮左上方，避免超出视口
  chatPos.value = {
    x: Math.max(8, window.innerWidth - CHAT_W - 16),
    y: Math.max(8, window.innerHeight - CHAT_H - 72)
  }
}
function closeChat() {
  chatOpen.value = false
}

// —— 启动按钮（圆形头像）可拖动：mousedown 起，mouseup 未移动则视为点击打开 ——
const launcherPos = ref({ x: 0, y: 0 })
function initLauncherPos() {
  launcherPos.value = {
    x: Math.max(8, window.innerWidth - 70),
    y: Math.max(8, window.innerHeight - 70)
  }
}
onMounted(() => {
  initLauncherPos()
})
let lstart = { x: 0, y: 0, px: 0, py: 0, moved: false }
function onLauncherDown(e: MouseEvent) {
  lstart = {
    x: e.clientX,
    y: e.clientY,
    px: launcherPos.value.x,
    py: launcherPos.value.y,
    moved: false
  }
  window.addEventListener('mousemove', onLauncherMove)
  window.addEventListener('mouseup', onLauncherUp)
  document.body.style.userSelect = 'none'
}
function onLauncherMove(e: MouseEvent) {
  const dx = e.clientX - lstart.x
  const dy = e.clientY - lstart.y
  if (Math.abs(dx) > 4 || Math.abs(dy) > 4) lstart.moved = true
  launcherPos.value = {
    x: Math.max(8, Math.min(window.innerWidth - 60, lstart.px + dx)),
    y: Math.max(8, Math.min(window.innerHeight - 60, lstart.py + dy))
  }
}
function onLauncherUp() {
  window.removeEventListener('mousemove', onLauncherMove)
  window.removeEventListener('mouseup', onLauncherUp)
  document.body.style.userSelect = ''
  // 仅当没有拖动时才打开对话（拖动后不触发点击）
  if (!lstart.moved) openChat()
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

// —— 语音朗读 ——
const speech = useSpeech()
const agentSettings = useAgentSettings()
function speakText(text: string) {
  const s = agentSettings.state.settings
  if (s && !s.voice_enabled) return // 总开关未启用则不朗读
  speech.speak(text, {
    voiceName: s?.voice_name,
    rate: s?.voice_rate ?? 1,
    pitch: s?.voice_pitch ?? 1,
    lang: s?.language === 'en' ? 'en-US' : 'zh-CN'
  })
}
function maybeAutoPlay(text: string) {
  const s = agentSettings.state.settings
  if (s && s.voice_enabled && s.voice_auto_play) speakText(text)
}

// —— 对话：多轮 + 历史（本地优先持久化，见 stores/agentChat）——
const input = ref('')
const view = ref<'chat' | 'history'>('chat')
const chatBody = ref<HTMLElement | null>(null)

function scrollToBottom() {
  nextTick(() => {
    if (chatBody.value) chatBody.value.scrollTop = chatBody.value.scrollHeight
  })
}
watch(() => chat.messages.length, scrollToBottom)
watch(view, (v) => {
  if (v === 'chat') scrollToBottom()
})

async function send() {
  const t = input.value.trim()
  if (!t) return
  input.value = ''
  await chat.send(t)
  const last = chat.messages[chat.messages.length - 1]
  if (last && last.role === 'agent') maybeAutoPlay(last.text)
}

// 历史会话侧栏
function openHistory() {
  view.value = 'history'
}
function backToChat() {
  view.value = 'chat'
}
function selectSession(id: string) {
  chat.selectSession(id)
  view.value = 'chat'
}
function newChat() {
  chat.newSession()
  view.value = 'chat'
}
function delSession(id: string) {
  chat.deleteSession(id)
}
</script>

<template>
  <!-- 紧凑启动按钮：可拖动；图标用情绪头像待机图，保留轻晃小动画 -->
  <button
    v-if="!chatOpen"
    class="agent-launcher"
    title="打开研究智能体（可拖动）"
    :style="{ left: launcherPos.x + 'px', top: launcherPos.y + 'px' }"
    @mousedown="onLauncherDown"
  >
    <img class="agent-launcher-img" :src="launcherIcon" alt="研究智能体" draggable="false" @dragstart.prevent />
  </button>

  <!-- 小对话窗：非模态浮层，可拖拽；对话时标题头像带小动画 -->
  <div
    v-if="chatOpen"
    class="agent-chat"
    :style="{ left: chatPos.x + 'px', top: chatPos.y + 'px', width: CHAT_W + 'px' }"
  >
    <div class="agent-chat-head" @mousedown="onChatDown">
      <span class="agent-chat-avatar" :class="{ thinking: chat.loading }">🤖</span>
      <span class="agent-chat-title">
        研究智能体
        <span v-if="chat.loading" class="agent-chat-dots"><i></i><i></i><i></i></span>
      </span>
      <div class="agent-chat-actions">
        <button
          v-if="view === 'chat'"
          class="agent-chat-btn"
          title="历史会话"
          @mousedown.stop
          @click.stop="openHistory"
        >🕘</button>
        <button
          v-else
          class="agent-chat-btn"
          title="返回对话"
          @mousedown.stop
          @click.stop="backToChat"
        >←</button>
        <button
          class="agent-chat-close"
          title="收起"
          @mousedown.stop
          @click.stop="closeChat"
        >×</button>
      </div>
    </div>

    <!-- 对话视图 -->
    <template v-if="view === 'chat'">
      <!-- 情绪头像：默认订阅 store 稳定会话，后端经 SSE 推送情绪状态 -->
      <div class="agent-emotion">
        <EmotionAvatar :session-id="emotionSessionId" :size="120" />
      </div>
      <div class="chat" ref="chatBody">
        <div
          v-for="(m, i) in chat.messages"
          :key="i"
          class="chat-row"
          :class="m.role"
        >
          <div class="chat-avatar">{{ m.role === 'agent' ? '🤖' : '🧑' }}</div>
          <div class="chat-bubble">
            <span class="cb-text">{{ m.text }}</span>
            <button
              v-if="m.role === 'agent'"
              class="cb-speak"
              title="朗读此条"
              @click="speakText(m.text)"
            >🔊</button>
          </div>
        </div>
      </div>
      <div class="chat-input">
        <el-input
          v-model="input"
          :placeholder="chat.loading ? '智能体思考中…' : '和智能体说点什么…'"
          @keydown.enter="send"
        />
        <el-button type="primary" :loading="chat.loading" @click="send">发送</el-button>
      </div>
    </template>

    <!-- 历史会话侧栏 -->
    <template v-else>
      <div class="chat-history">
        <div class="history-head">
          <span>历史会话</span>
          <el-button size="small" type="primary" @click="newChat">＋ 新对话</el-button>
        </div>
        <div class="history-list">
          <div v-if="chat.sessions.length === 0" class="history-empty">还没有对话记录</div>
          <div
            v-for="s in chat.sessions"
            :key="s.id"
            class="history-item"
            @click="selectSession(s.id)"
          >
            <div class="history-item-main">
              <div class="history-title">{{ s.title }}</div>
              <div class="history-sub">
                {{ s.messages.length }} 条 · {{ new Date(s.updatedAt).toLocaleDateString() }}
              </div>
            </div>
            <button
              class="history-del"
              title="删除"
              @click.stop="delSession(s.id)"
            >🗑</button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* 启动按钮：用情绪头像裁成圆形作为按钮本身，不再露出紫色背景 */
.agent-launcher {
  position: fixed;
  left: 0;
  top: 0;
  right: auto;
  bottom: auto;
  z-index: 55;
  width: 52px;
  height: 52px;
  border: none;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 8px 22px rgba(20, 30, 60, 0.18);
  cursor: grab;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  transition: box-shadow 0.2s ease;
}
.agent-launcher:hover {
  box-shadow: 0 10px 28px rgba(20, 30, 60, 0.26);
}
.agent-launcher:active {
  cursor: grabbing;
  transform: scale(0.96);
}
.agent-launcher-img {
  width: 100%;
  height: 100%;
  display: inline-block;
  border-radius: 50%;
  object-fit: cover;
  animation: agent-bob 2.6s ease-in-out infinite;
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
  gap: 8px;
  padding: 10px 12px;
  background: linear-gradient(160deg, #6a5cff 0%, #2b6cff 100%);
  color: #fff;
  cursor: move;
  flex: 0 0 auto;
}
/* 标题上的智能体头像：待机轻晃；思考时抖动（对话时的小动画） */
.agent-chat-avatar {
  font-size: 18px;
  line-height: 1;
  display: inline-block;
  animation: agent-bob 2.6s ease-in-out infinite;
}
.agent-chat-avatar.thinking {
  animation: agent-shake 0.9s ease-in-out infinite;
}
@keyframes agent-bob {
  0%,
  100% {
    transform: translateY(0) rotate(0deg);
  }
  25% {
    transform: translateY(-2px) rotate(-6deg);
  }
  75% {
    transform: translateY(-2px) rotate(6deg);
  }
}
@keyframes agent-shake {
  0%,
  100% {
    transform: translateX(0) rotate(0deg);
  }
  20% {
    transform: translateX(-2px) rotate(-8deg);
  }
  50% {
    transform: translateX(2px) rotate(8deg);
  }
  80% {
    transform: translateX(-1px) rotate(-4deg);
  }
}
.agent-chat-title {
  flex: 1 1 auto;
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 4px;
}
/* “思考中”省略号动画 */
.agent-chat-dots {
  display: inline-flex;
  gap: 3px;
}
.agent-chat-dots i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #fff;
  opacity: 0.6;
  animation: agent-dot 1.2s infinite ease-in-out;
}
.agent-chat-dots i:nth-child(2) {
  animation-delay: 0.2s;
}
.agent-chat-dots i:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes agent-dot {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}
.agent-chat-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.agent-chat-btn {
  border: none;
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.agent-chat-btn:hover {
  background: rgba(255, 255, 255, 0.35);
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
  display: flex;
  align-items: center;
  justify-content: center;
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
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
.cb-text {
  flex: 1 1 auto;
  white-space: pre-wrap;
}
.cb-speak {
  flex: 0 0 auto;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  line-height: 1.4;
  padding: 0 2px;
  opacity: 0.5;
  transition: opacity 0.15s;
}
.cb-speak:hover {
  opacity: 1;
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
/* 历史会话侧栏 */
.chat-history {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  font-size: 13px;
  font-weight: 600;
  color: #3a4256;
  border-bottom: 1px solid #eef0f2;
}
.history-list {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.history-empty {
  text-align: center;
  color: #9aa3b2;
  font-size: 12px;
  padding: 24px 0;
}
.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 10px;
  background: #f6f8fc;
  border: 1px solid #eef0f2;
  cursor: pointer;
  transition: background 0.15s;
}
.history-item:hover {
  background: #eef3ff;
}
.history-item-main {
  flex: 1 1 auto;
  min-width: 0;
}
.history-title {
  font-size: 13px;
  color: #1f2329;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.history-sub {
  font-size: 11px;
  color: #9aa3b2;
  margin-top: 2px;
}
.history-del {
  flex: 0 0 auto;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  opacity: 0.5;
  padding: 2px 4px;
}
.history-del:hover {
  opacity: 1;
}
</style>
