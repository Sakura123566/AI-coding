<script setup lang="ts">
/**
 * 情绪 Avatar 组件（队员2 直接用）
 * 用法：<EmotionAvatar session-id="abc123" api-base="http://localhost:8000" />
 *
 * api-base 解析优先级（便于后端队友联调，无需重新打包）：
 *   1. URL 查询参数 ?emotionApi=  （最高，联调时直接拼在网址后）
 *   2. 组件 prop api-base
 *   3. 构建期环境变量 import.meta.env.VITE_API_BASE_URL
 *   4. 默认值 http://localhost:8000
 *
 * 依赖：src/assets/emotion-map.json（状态->webp 文件名），webp 全部放 public/emojis/。
 */
import { ref, onMounted, onUnmounted } from 'vue'
import emotionMap from '@/assets/emotion-map.json'

const props = defineProps({
  sessionId: { type: String, required: true },
  apiBase: { type: String, default: '' },
  size: { type: Number, default: 160 },
})

// 解析后端地址：URL 参数优先，其次 prop，其次构建期环境变量，最后默认 localhost
function resolveApiBase(): string {
  const params = new URLSearchParams(window.location.search)
  const fromUrl = params.get('emotionApi')
  if (fromUrl) return fromUrl
  if (props.apiBase) return props.apiBase
  const fromEnv = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (fromEnv) return fromEnv
  return 'http://localhost:8000'
}

const baseUrl = import.meta.env.BASE_URL || '/'

const map = emotionMap as Record<string, string>
const emotion = ref('待机')
const file = ref(map['待机'] || '')
let es: EventSource | null = null
let timer: ReturnType<typeof setTimeout> | null = null

function show(name: string) {
  emotion.value = name
  file.value = map[name] || map['待机'] || ''
}

const apiBase = resolveApiBase()

onMounted(() => {
  es = new EventSource(
    `${apiBase}/api/emotion/stream?session_id=${encodeURIComponent(props.sessionId)}`
  )
  es.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data)
      show(ev.emotion)
      if (ev.is_temporary) {
        if (timer) clearTimeout(timer)
        timer = setTimeout(
          () => show(ev.restore_state || ev.base_state),
          (ev.temporary_duration ?? 3) * 1000
        )
      }
    } catch {
      /* 忽略非 JSON / 脏帧 */
    }
  }
  es.onerror = () => {
    // EventSource 会自动重连，这里不做额外处理
  }
})

onUnmounted(() => {
  es?.close()
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="emotion-avatar">
    <img
      :src="`${baseUrl}emojis/${file}`"
      :alt="emotion"
      :style="{ width: `${size}px`, height: `${size}px` }"
    />
    <span class="emotion-label">{{ emotion }}</span>
  </div>
</template>

<style scoped>
.emotion-avatar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.emotion-avatar img {
  object-fit: contain;
}
.emotion-label {
  font-size: 12px;
  color: #666;
}
</style>
