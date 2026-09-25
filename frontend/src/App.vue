<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Search,
  Star,
  Clock,
  Share,
  Folder,
  FullScreen,
  Close,
  Expand,
  Fold,
  Setting,
  Document,
  User,
  SwitchButton,
  MagicStick
} from '@element-plus/icons-vue'
import DemoModeBanner from './components/DemoModeBanner.vue'
import TopicInput from './components/TopicInput.vue'
import PaperList from './components/PaperList.vue'
import ResearchReport from './components/ResearchReport.vue'
import AgentBubble from './components/AgentBubble.vue'
import FavoritesView from './components/FavoritesView.vue'
import HistoryView from './components/HistoryView.vue'
import { useResearch } from './composables/useResearch'
import { useKpStore, type KpMode } from './stores/knowledgeParty'
import { useUserStore } from './stores/user'
import UserAvatar from './components/UserAvatar.vue'
import UserProfileDrawer from './components/UserProfileDrawer.vue'
import AgentSettingsDrawer from './components/AgentSettingsDrawer.vue'
import WeeklyReportDrawer from './components/WeeklyReportDrawer.vue'
import SkillManagerDrawer from './components/SkillManagerDrawer.vue'
import { useAgentSettings } from './composables/useAgentSettings'
import AuthDialog from './components/AuthDialog.vue'

const store = useKpStore()
const { topic, submit } = useResearch()
const userStore = useUserStore()
userStore.init() // 启动若有 token 则异步刷新画像

// 智能体设置（含语音开关/音色/语速/音调）：token 就绪即加载，供语音朗读使用
const agentSettings = useAgentSettings()
watch(
  () => userStore.token,
  (t) => {
    if (t) agentSettings.load(t)
  },
  { immediate: true }
)

// —— 用户登录 / 资料 ——
const authVisible = ref(false)
const profileVisible = ref(false)
const agentSettingsVisible = ref(false)
const weeklyVisible = ref(false)
const skillManagerVisible = ref(false)
const popoverVisible = ref(false)

// 登录后点头像 -> 在侧边头像处弹出小菜单（非居中弹窗）
function openProfile() {
  popoverVisible.value = false
  profileVisible.value = true
}
function openAgentSettings() {
  popoverVisible.value = false
  agentSettingsVisible.value = true
}
function openWeekly() {
  popoverVisible.value = false
  weeklyVisible.value = true
}
function openSkillManager() {
  popoverVisible.value = false
  skillManagerVisible.value = true
}
// 未登录时点头像 -> 登录/注册
function openAuth() {
  authVisible.value = true
}
// 退出登录（带确认）
async function onLogoutClick() {
  popoverVisible.value = false
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '退出登录', {
      type: 'warning',
      confirmButtonText: '退出',
      cancelButtonText: '取消'
    })
    userStore.logout()
    ElMessage.success('已退出登录')
  } catch {
    /* 用户取消 */
  }
}

// —— 布局状态 ——
// 左：图标导航（默认只显示图标，点击第一个图标展开显示名字+近期搜索）；中：模式视图；右：方向概览
const leftExpanded = ref(false) // 默认只显示图标
const rightCollapsed = ref(true) // 默认收起，查找论文后自动弹出
const rightMaximized = ref(false)
const leftWidth = ref(220) // 展开后的左栏宽度（可拖拽）
const rightWidth = ref(460) // 右方向概览面板可拖拽宽度

const leftStyle = computed(() => ({
  width: leftExpanded.value ? leftWidth.value + 'px' : '56px'
}))
const rightStyle = computed(() => ({
  width: rightCollapsed.value ? '0' : rightWidth.value + 'px'
}))

function toggleLeft() {
  leftExpanded.value = !leftExpanded.value
}
function toggleRight() {
  rightCollapsed.value = !rightCollapsed.value
}
function toggleMaximize() {
  rightMaximized.value = !rightMaximized.value
  if (rightMaximized.value) rightCollapsed.value = false
}

// —— 拖拽改宽（左导航 / 右概览）——
let resizing: 'left' | 'right' | null = null
let startX = 0
let startW = 0
function startResize(side: 'left' | 'right', e: MouseEvent) {
  resizing = side
  startX = e.clientX
  startW = side === 'left' ? leftWidth.value : rightWidth.value
  window.addEventListener('mousemove', onResizeMove)
  window.addEventListener('mouseup', onResizeUp)
  document.body.style.userSelect = 'none'
}
function onResizeMove(e: MouseEvent) {
  if (!resizing) return
  const dx = e.clientX - startX
  if (resizing === 'left') {
    leftWidth.value = Math.min(320, Math.max(140, startW + dx))
  } else {
    rightWidth.value = Math.min(820, Math.max(320, startW - dx))
  }
}
function onResizeUp() {
  resizing = null
  window.removeEventListener('mousemove', onResizeMove)
  window.removeEventListener('mouseup', onResizeUp)
  document.body.style.userSelect = ''
}

const navItems: { key: KpMode; label: string; icon: any }[] = [
  { key: 'search', label: '搜索', icon: Search },
  { key: 'favorites', label: '收藏', icon: Star },
  { key: 'history', label: '历史', icon: Clock },
  { key: 'graph', label: '图谱', icon: Share }
]

// —— 搜索 ——
const phaseText = computed(() =>
  store.phase === 'analyzing' ? '已找到论文，正在生成研究导航…' : '正在检索论文…'
)

// 没找到相关文献时的趣味表达（避免「假装查到了」）；按搜索次数轮换，避免同一句刷屏
const noMatchPhrases = [
  (t: string) => `这场派对还没邀请到和「${t}」相关的知识点，换个主题把它们叫来吧`,
  (t: string) => `暂时没有和「${t}」相关的论文来入场，试试别的关键词`,
  (t: string) => `还没匹配到和「${t}」相关的文献，换个方向再来开派对`
]
const phraseIdx = ref(0)
function rotatePhrase() {
  phraseIdx.value = (phraseIdx.value + 1) % Math.max(1, noMatchPhrases.length)
}
const emptyText = computed(() =>
  store.backendMessage || noMatchPhrases[phraseIdx.value % noMatchPhrases.length](store.topic)
)

function onSearch() {
  rotatePhrase()
  submit()
}

// 「图谱」：点击后打开独立的 29f5 知识图谱网页（/kg/index.html，与线上 29f5 1:1 克隆）
function openKnowledgeGraphPage() {
  const base = import.meta.env.BASE_URL || '/'
  const url = `${base.replace(/\/$/, '')}/kg/index.html`
  window.open(url, '_blank', 'noopener')
}
function onNav(item: { key: KpMode; label: string; icon: any }) {
  if (item.key === 'graph') {
    openKnowledgeGraphPage()
  } else {
    store.setMode(item.key)
  }
}
function onSelect(t: string) {
  store.setMode('search') // 点历史记录自动切回搜索界面，无需手动切换
  topic.value = t
  rotatePhrase()
  submit()
}

// 分页：「加载更多」
const pageSize = 6
const visibleCount = ref(pageSize)
const loadingMore = ref(false)
const visiblePapers = computed(() => store.papers.slice(0, visibleCount.value))
const hasMore = computed(() => visibleCount.value < store.papers.length)
watch(
  () => store.papers,
  (p) => {
    visibleCount.value = pageSize
    // 查到论文后自动展开右侧「方向概览」（用户手动收起后，下次搜索仍会重新弹出）
    if (p && p.length > 0) rightCollapsed.value = false
  }
)
async function loadMore() {
  if (loadingMore.value || !hasMore.value) return
  loadingMore.value = true
  await new Promise((r) => setTimeout(r, 450))
  visibleCount.value = Math.min(visibleCount.value + pageSize, store.papers.length)
  loadingMore.value = false
}

// 空间切换（左导航底部图标下拉）
function onSpaceCmd(cmd: any) {
  if (cmd === 'add') {
    createSpace()
  } else if (cmd && cmd.type === 'switch') {
    store.switchSpace(cmd.id)
  }
}
async function createSpace() {
  try {
    const { value } = await ElMessageBox.prompt('给新空间起个名字', '新建空间', {
      inputValue: '新空间',
      confirmButtonText: '创建',
      cancelButtonText: '取消'
    })
    const name = (value ?? '').trim()
    if (name) store.addSpace(name)
  } catch {
    /* 用户取消 */
  }
}
</script>

<template>
  <DemoModeBanner />
  <div class="layout" :class="{ maximized: rightMaximized }">
    <!-- 左：图标导航（默认只图标；点第一个图标展开显示名字+近期搜索） -->
    <aside class="rail" :class="{ expanded: leftExpanded }" :style="leftStyle">
      <div class="rail-top">
        <el-button
          :icon="leftExpanded ? Fold : Expand"
          circle
          size="small"
          title="展开 / 收起侧栏"
          @click="toggleLeft"
        />
      </div>

      <nav class="rail-nav">
        <div
          v-for="item in navItems"
          :key="item.key"
          class="rail-item"
          :class="{ active: store.mode === item.key }"
          :title="item.label"
          @click="onNav(item)"
        >
          <el-icon class="rail-icon"><component :is="item.icon" /></el-icon>
          <span v-if="leftExpanded" class="rail-label">{{ item.label }}</span>
        </div>
      </nav>

      <!-- 展开后显示近期搜索记录（前几个版本样式） -->
      <div v-if="leftExpanded" class="rail-recent">
        <div class="rail-recent-title">近期搜索</div>
        <el-tag
          v-for="h in store.currentHistory.slice(0, 8)"
          :key="h.q"
          size="small"
          effect="plain"
          class="rail-recent-tag"
          @click="onSelect(h.q)"
        >{{ h.q }}</el-tag>
        <div v-if="!store.currentHistory.length" class="rail-recent-empty">还没有搜索记录</div>
      </div>

      <div class="rail-bottom">
        <el-dropdown trigger="click" @command="onSpaceCmd">
          <el-button :icon="Folder" circle size="small" title="空间切换" />
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-for="s in store.spaces"
                :key="s.id"
                :command="{ type: 'switch', id: s.id }"
              >{{ s.name }}</el-dropdown-item>
              <el-dropdown-item command="add" divided>+ 新建空间</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <!-- 登录后：点头像在侧边弹出小菜单（非居中） -->
        <el-popover
          v-if="userStore.isLoggedIn"
          v-model:visible="popoverVisible"
          placement="right-start"
          :width="208"
          trigger="click"
          popper-class="avatar-popover"
        >
          <template #reference>
            <UserAvatar :expanded="leftExpanded" />
          </template>
          <div class="avatar-menu">
            <button class="am-item" @click="openProfile">
              <el-icon><User /></el-icon><span>我的资料</span>
            </button>
            <button class="am-item" @click="openAgentSettings">
              <el-icon><Setting /></el-icon><span>智能体设置</span>
            </button>
            <button class="am-item" @click="openWeekly">
              <el-icon><Document /></el-icon><span>周报</span>
            </button>
            <button class="am-item" @click="openSkillManager">
              <el-icon><MagicStick /></el-icon><span>技能管理</span>
            </button>
            <div class="am-divider" />
            <button class="am-item am-danger" @click="onLogoutClick">
              <el-icon><SwitchButton /></el-icon><span>退出登录</span>
            </button>
          </div>
        </el-popover>
        <!-- 未登录：点头像打开登录/注册 -->
        <UserAvatar v-else :expanded="leftExpanded" @click="openAuth" />
      </div>

      <div v-if="leftExpanded" class="resizer resizer-left" @mousedown="startResize('left', $event)" />
    </aside>

    <!-- 中栏：按模式切换的视图（搜索 / 收藏 / 历史 / 图谱） -->
    <main class="content">
      <template v-if="store.mode === 'search'">
        <div class="search-panel" :class="{ centered: !store.searched }">
          <div class="search-header">
            <div class="hero" :class="{ compact: store.searched }">
              <div class="hero-en">Knowledge Party</div>
              <div class="hero-zh">知识派对</div>
            </div>
            <TopicInput v-model="topic" :loading="store.loading" @submit="onSearch" />
          </div>

          <template v-if="store.searched">
            <el-alert
              v-if="store.error"
              :title="store.error"
              type="error"
              show-icon
              class="alert"
            >
              <el-button
                v-if="store.retryableError"
                size="small"
                type="danger"
                plain
                class="retry-btn"
                @click="store.retry()"
              >重试</el-button>
            </el-alert>

            <div v-else-if="store.loading" class="loading-box">
              <div class="loading-text">{{ phaseText }}</div>
              <el-skeleton :rows="8" animated class="skeleton" />
            </div>

            <section v-else-if="store.report || store.papers.length" class="results">
              <div v-if="store.resolvedKeyword" class="resolved-kw">
                已按「{{ store.resolvedKeyword }}」检索
              </div>
              <el-alert
                v-if="store.warnings.some((w) => w.includes('本地样例') || w.toLowerCase().includes('mock'))"
                type="warning"
                :closable="false"
                show-icon
                class="warn-banner"
              >
                <template #title>本地样例模式：后端尚未接入真实模型，以下报告为示例数据</template>
              </el-alert>
              <PaperList :papers="visiblePapers" />
              <div v-if="hasMore" class="loadmore">
                <el-button :loading="loadingMore" @click="loadMore">
                  加载更多（还有 {{ store.papers.length - visibleCount }} 篇）
                </el-button>
              </div>
              <div v-else class="nomore">已经到底啦，没有更多论文 🎉</div>
            </section>

            <el-empty
              v-else
              class="empty-state"
              :description="emptyText"
              :image-size="110"
            />
          </template>
        </div>
      </template>

      <FavoritesView v-else-if="store.mode === 'favorites'" />
      <HistoryView v-else-if="store.mode === 'history'" />
    </main>

    <!-- 右栏：方向概览（研究导航报告），可拖宽、可收起、可放大整页 -->
    <aside
      class="right-panel"
      :class="{ collapsed: rightCollapsed, maximized: rightMaximized }"
      :style="rightStyle"
    >
      <div class="rp-head">
        <span class="rp-title">方向概览</span>
        <div class="rp-actions">
          <el-button
            text
            size="small"
            :icon="FullScreen"
            title="放大到整页"
            @click="toggleMaximize"
          />
          <el-button
            v-if="!rightMaximized"
            text
            size="small"
            :icon="Close"
            title="收起"
            @click="toggleRight"
          />
        </div>
      </div>

      <div class="rp-body">
        <ResearchReport
          v-if="store.report || store.reportError"
          :report="store.report"
          :papers="store.papers"
          :report-error="store.reportError"
        />
        <div v-else class="panel-empty">检索后这里会生成方向概览</div>
      </div>

      <div
        v-if="!rightCollapsed && !rightMaximized"
        class="resizer resizer-right"
        @mousedown="startResize('right', $event)"
      />
    </aside>

    <!-- 智能体浮标（右侧可拖动椭圆，点击弹出小对话窗，非模态不挡页面） -->
    <AgentBubble />

    <!-- 用户：资料抽屉 + 智能体设置 + 周报 + 登录/注册弹窗 -->
    <UserProfileDrawer v-model="profileVisible" />
    <AgentSettingsDrawer v-model="agentSettingsVisible" />
    <WeeklyReportDrawer v-model="weeklyVisible" />
    <SkillManagerDrawer v-model="skillManagerVisible" />
    <AuthDialog v-model="authVisible" />

    <!-- 收起后的浮起展开按钮（仅右栏） -->
    <button v-if="rightCollapsed" class="rail-open rail-open-right" title="展开方向概览" @click="toggleRight">«</button>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.layout.maximized .rail,
.layout.maximized .content {
  display: none;
}

/* 左：图标导航 */
.rail {
  flex: 0 0 auto;
  height: 100vh;
  overflow: hidden;
  padding: 12px 4px;
  border-right: 1px solid #eaecef;
  background: #fbfbfc;
  box-sizing: border-box;
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.rail.expanded {
  padding: 12px 8px;
  align-items: stretch;
}
.rail-top {
  margin-bottom: 14px;
  text-align: center;
}
.rail-nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 0 0 auto;
}
.rail-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px;
  border-radius: 10px;
  color: #555;
  font-size: 14px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s, color 0.15s;
}
.rail.expanded .rail-item {
  padding: 9px 10px;
}
.rail-item:hover {
  background: #e8f0fe;
}
.rail-item.active {
  background: var(--el-color-primary);
  color: #fff;
  font-weight: 600;
}
.rail-icon {
  font-size: 18px;
  flex: 0 0 auto;
}
.rail-label {
  white-space: nowrap;
}
.rail-bottom {
  margin-top: auto;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

/* 展开后的近期搜索 */
.rail-recent {
  margin: 10px 2px 12px;
  padding-top: 10px;
  border-top: 1px dashed #e3e6eb;
}
.rail-recent-title {
  font-size: 12px;
  color: #9aa0a6;
  margin-bottom: 8px;
}
.rail-recent-tag {
  cursor: pointer;
  margin: 0 6px 6px 0;
}
.rail-recent-tag:hover {
  color: var(--el-color-primary);
}
.rail-recent-empty {
  font-size: 12px;
  color: #b6bcc6;
}

/* 中栏 */
.content {
  flex: 1 1 auto;
  height: 100vh;
  overflow-y: auto;
  padding: 32px 40px;
  background: #f7f8fa;
  box-sizing: border-box;
}
.search-panel {
  display: flex;
  flex-direction: column;
  min-height: 100%;
}
.search-panel.centered {
  justify-content: center;
  overflow: hidden;
}
.search-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: #f7f8fa;
  padding: 4px 0 16px;
  margin-bottom: 8px;
  border-bottom: 1px solid #eef0f2;
}
.search-panel.centered .search-header {
  border-bottom: none;
}
.hero {
  text-align: center;
  margin-bottom: 18px;
  transition: all 0.2s ease;
  font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', system-ui,
    -apple-system, 'Helvetica Neue', Arial, sans-serif;
}
.hero.compact {
  margin-bottom: 12px;
}
.hero-en {
  font-size: 40px;
  font-weight: 800;
  line-height: 1.35;
  letter-spacing: 0;
  padding-bottom: 4px;
  background: linear-gradient(120deg, #2b6cff 0%, #6a5cff 55%, #9b6bff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hero.compact .hero-en {
  font-size: 24px;
  padding-bottom: 2px;
}
.hero-zh {
  margin-top: 14px;
  font-size: 16px;
  font-weight: 400;
  color: #9aa0a6;
  letter-spacing: 4px;
}
.hero.compact .hero-zh {
  margin-top: 8px;
  font-size: 13px;
}
.loading-box {
  margin-top: 8px;
}
.loading-text {
  font-size: 14px;
  color: #5a6b8c;
  margin-bottom: 14px;
}
.alert {
  margin-top: 8px;
}
.retry-btn {
  margin-top: 8px;
}
.results {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1000px;
  margin-top: 8px;
}
.resolved-kw {
  font-size: 13px;
  color: #5a6b8c;
  background: #eef3ff;
  border: 1px solid #dbe6ff;
  border-radius: 8px;
  padding: 6px 10px;
}
.warn-banner {
  margin-bottom: 4px;
}
.empty-state {
  margin-top: 48px;
}
.loadmore {
  display: flex;
  justify-content: center;
  margin: 20px 0 8px;
}
.nomore {
  text-align: center;
  color: #9aa0a6;
  font-size: 13px;
  margin: 16px 0 4px;
}

/* 中间模式视图（图谱等） */
.mode-view {
  max-width: 1000px;
}
.mode-title {
  font-size: 18px;
  font-weight: 700;
  color: #1f2329;
  margin: 0 0 16px;
}

/* 右栏 */
.right-panel {
  flex: 0 0 auto;
  height: 100vh;
  overflow: hidden;
  border-left: 1px solid #eaecef;
  background: #fff;
  box-sizing: border-box;
  position: relative;
  display: flex;
  flex-direction: column;
}
.right-panel.collapsed {
  border-left: none;
}
.right-panel.maximized {
  position: fixed;
  inset: 0;
  width: 100% !important;
  z-index: 50;
}
.rp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid #eef0f2;
  flex: 0 0 auto;
}
.rp-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2329;
}
.rp-actions {
  display: flex;
  gap: 2px;
}
.rp-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 14px;
}
.panel-empty {
  color: #9aa0a6;
  font-size: 13px;
  text-align: center;
  padding: 48px 12px;
}

/* 拖拽手柄：加宽判定范围，方便抓取滑动 */
.resizer {
  position: absolute;
  top: 0;
  width: 12px;
  height: 100%;
  cursor: col-resize;
  z-index: 5;
}
/* 透明扩展命中区（左右各 7px），更易抓 */
.resizer::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: -7px;
  right: -7px;
}
.resizer:hover {
  background: rgba(43, 108, 255, 0.18);
}
.resizer-left {
  right: -6px;
}
.resizer-right {
  left: -6px;
}

/* 收起后浮起展开按钮（仅右栏） */
.rail-open {
  position: fixed;
  top: 14px;
  right: 4px;
  z-index: 60;
  width: 22px;
  height: 40px;
  border: 1px solid #e3e6eb;
  background: #fff;
  color: #5a6b8c;
  cursor: pointer;
  border-radius: 6px;
  font-size: 14px;
}
</style>

<!-- 头像弹出菜单：el-popover 默认 teleport 到 body，需非 scoped 样式 -->
<style>
.avatar-popover {
  padding: 6px !important;
}
.avatar-menu {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.am-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border: none;
  background: transparent;
  border-radius: 8px;
  color: #1f2329;
  font-size: 14px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}
.am-item:hover {
  background: #eef2f7;
}
.am-item .el-icon {
  font-size: 16px;
  color: #5a6b8c;
}
.am-item.am-danger {
  color: #c0392b;
}
.am-item.am-danger .el-icon {
  color: #c0392b;
}
.am-item.am-danger:hover {
  background: #fdecec;
}
.am-divider {
  height: 1px;
  background: #eef0f2;
  margin: 4px 0;
}
</style>
