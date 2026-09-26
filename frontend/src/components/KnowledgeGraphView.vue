<template>
  <div class="kg-view">
    <!-- 顶部一条：返回首页 + 主题 + 换主题 / 刷新 / 新窗口 -->
    <div class="kg-bar">
      <button class="kg-back" @click="backHome">
        <el-icon><ArrowLeft /></el-icon>
        <span>返回首页</span>
      </button>
      <!-- 「当前主题」显示的是图谱里真实的网络中心词：点节点钻进去时会同步变化 -->
      <span class="kg-tip">
        当前主题：<b>{{ shownTopic || '未指定' }}</b>
      </span>
      <div class="kg-grow" />
      <el-input
        v-model="kw"
        class="kg-input"
        size="small"
        placeholder="换个主题重新生成图谱"
        @keyup.enter="reload"
      />
      <el-button size="small" type="primary" @click="reload">生成</el-button>
      <el-button size="small" :icon="Refresh" title="重新加载" @click="reload">刷新</el-button>
      <el-button size="small" :icon="Promotion" title="用浏览器新标签打开" @click="openExternal">
        新窗口
      </el-button>
    </div>

    <!-- 图谱页本身是一个独立的静态页，这里用内嵌框架把它装进应用里，
         于是「点图谱」不再弹出一个新网页，而是在应用内换到这一页。 -->
    <iframe class="kg-frame" :src="src" frameborder="0" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowLeft, Promotion, Refresh } from '@element-plus/icons-vue'
import { useKpStore } from '../stores/knowledgeParty'

const store = useKpStore()
const kw = ref(store.topic || '')
const nonce = ref(0)
const base = import.meta.env.BASE_URL || '/'

// 图谱页会把「当前网络中心词」用 postMessage 报上来（点节点钻进去时也会跟着变），
// 这里接住它，让左上角显示的永远是真实的网络中心，而不是用户当初输入的那个词。
const liveCenter = ref('')

function onMessage(e: MessageEvent) {
  const d = e.data as { source?: string; type?: string; center?: string } | null
  if (!d || d.source !== 'kg' || d.type !== 'center') return
  liveCenter.value = String(d.center || '')
}
onMounted(() => window.addEventListener('message', onMessage))
onBeforeUnmount(() => window.removeEventListener('message', onMessage))

const shownTopic = computed(() => liveCenter.value || kw.value.trim() || '')

// 主题或刷新计数一变就换 src —— 换 src 等于让内嵌框架重新加载整个图谱页。
const src = computed(() => {
  const q = new URLSearchParams()
  const t = kw.value.trim()
  if (t) q.set('kw', t)
  q.set('_n', String(nonce.value))
  return `${base.replace(/\/$/, '')}/kg/index.html?${q.toString()}`
})

function backHome() {
  store.setMode('search')
}
function reload() {
  liveCenter.value = '' // 换了主题，先清掉旧的中心词显示，免得闪一下旧值
  nonce.value += 1
}
function openExternal() {
  window.open(src.value, '_blank', 'noopener')
}
</script>

<style scoped>
.kg-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #f5f7fb;
}
.kg-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: #fff;
  border-bottom: 1px solid #e6ebf2;
  flex: 0 0 auto;
}
.kg-grow {
  flex: 1;
}
.kg-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid #d6deea;
  border-radius: 8px;
  background: #fff;
  color: #2b3a55;
  font-size: 13px;
  cursor: pointer;
}
.kg-back:hover {
  background: #f0f5ff;
  border-color: #9dbaf0;
}
.kg-tip {
  font-size: 13px;
  color: #6b7688;
}
.kg-tip b {
  color: var(--brand, #2f5fe0);
}
.kg-input {
  width: 220px;
}
.kg-frame {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  border: 0;
  background: #fff;
}
</style>
