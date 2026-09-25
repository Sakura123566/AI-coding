<script setup lang="ts">
import { computed, ref } from 'vue'
import { Star, StarFilled } from '@element-plus/icons-vue'
import { useKpStore } from '../stores/knowledgeParty'
import type { Paper } from '../services/research'
import { ElMessage, ElMessageBox } from 'element-plus'

defineProps<{
  papers: Paper[]
}>()

const store = useKpStore()


const NO_INFO_ABSTRACT = /^信息有限[，,](?:无法(?:翻译|提供)摘要|无法提供有效摘要)/

function cleanAbstract(value?: string): string {
  const text = (value || '').trim()
  return text && !NO_INFO_ABSTRACT.test(text) ? text : ''
}

function displayAbstract(p: Paper): string {
  const original = cleanAbstract(p.abstract)
  if (!original) return ''
  return cleanAbstract(p.abstractSummaryZh) || cleanAbstract(p.abstractZh) || original
}

function hasOriginalAbstract(p: Paper): boolean {
  const original = cleanAbstract(p.abstract)
  return !!original && original !== displayAbstract(p)
}
function authorsText(p: Paper): string {
  if (!p.authors || p.authors.length === 0) return '作者未知'
  return p.authors.join(', ')
}
function publishText(p: Paper): string {
  return p.year ? `${p.year} 年` : '年份未知'
}

// —— 星标弹窗：选收藏夹（跨收藏夹收藏/移除）——
const favDialogVisible = ref(false)
const favTarget = ref<Paper | null>(null)
// 当前论文已落入的收藏夹 id 列表（随 store 变化响应式更新）
const favTargetIn = computed<string[]>(() =>
  favTarget.value ? store.favoriteSpaceIdsOf(favTarget.value.id) : []
)

function openFav(p: Paper) {
  favTarget.value = p
  favDialogVisible.value = true
}
function toggleFavSpace(spaceId: string) {
  const p = favTarget.value
  if (!p) return
  if (favTargetIn.value.includes(spaceId)) {
    store.removeFromSpace(spaceId, p.id)
  } else {
    store.addToSpace(spaceId, p)
  }
}
function cancelAllFav() {
  const p = favTarget.value
  if (!p) return
  store.cancelAllFavorites(p.id)
  ElMessage.success('已取消全部收藏')
}

// 星标主入口：根据「按主题自动归类」开关决定直接归入主题收藏夹，还是弹出手动选择
function onStar(p: Paper) {
  // 已收藏：打开弹窗做管理（移入其它收藏夹 / 取消）
  if (store.isFavInAny(p.id)) {
    openFav(p)
    return
  }
  const topic = (store.topic || '').trim()
  if (store.autoSortByTopic && topic) {
    // 默认按当前主题归入收藏夹：不存在则自动创建（不切换当前收藏夹）
    const sid = store.ensureSpaceByName(topic)
    store.addToSpace(sid, p)
    store.setFavoriteDestination(sid)
    ElMessage.success(`已收藏到「${topic}」`)
  } else {
    // 开关关闭或主题为空：退回手动选择收藏夹
    openFav(p)
  }
}

// 在弹窗里直接新建收藏夹，并把当前论文收进去
async function createSpaceAndAdd() {
  try {
    const { value } = await ElMessageBox.prompt('输入新收藏夹名称', '新建收藏夹', {
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空',
      confirmButtonText: '创建',
      cancelButtonText: '取消'
    })
    const name = value?.trim()
    const p = favTarget.value
    if (!name || !p) return
    store.addSpace(name)
    const newId = store.currentSpaceId
    store.addToSpace(newId, p)
    ElMessage.success(`已创建「${name}」并收藏本文献`)
  } catch {
    /* 取消 */
  }
}

async function addTagFor(p: Paper) {
  try {
    const { value } = await ElMessageBox.prompt('输入标签名（回车添加）', '给收藏打标签', {
      inputPattern: /\S+/,
      inputErrorMessage: '标签不能为空',
      confirmButtonText: '添加',
      cancelButtonText: '取消'
    })
    if (value && value.trim()) {
      store.addTag(p.id, value.trim())
      ElMessage.success('已添加标签')
    }
  } catch {
    /* 取消 */
  }
}
</script>

<template>
  <div class="paper-list">
    <el-empty v-if="papers.length === 0" description="暂无论文" />
    <el-card
      v-for="(p, i) in papers"
      :key="i"
      class="paper-card"
      shadow="hover"
    >
      <div class="paper-head">
        <div class="paper-title">
          <a
            v-if="p.url"
            :href="p.url"
            target="_blank"
            rel="noopener"
            :title="p.title"
            @click="store.markViewed(p)"
          >{{ p.titleZh || p.title }}</a>
          <span v-else class="paper-title-text" :title="p.title">{{ p.titleZh || p.title }}</span>
          <div v-if="p.titleZh && p.titleZh !== p.title" class="paper-title-original">{{ p.title }}</div>
        </div>
        <el-button
          class="fav-btn"
          :type="store.isFavInAny(p.id) ? 'warning' : 'info'"
          :plain="!store.isFavInAny(p.id)"
          circle
          size="small"
          :title="store.isFavInAny(p.id) ? '管理收藏' : '收藏到主题收藏夹'"
          @click="onStar(p)"
        >
          <el-icon>
            <component :is="store.isFavInAny(p.id) ? StarFilled : Star" />
          </el-icon>
        </el-button>
      </div>

      <p v-if="displayAbstract(p)" class="paper-abstract">{{ displayAbstract(p) }}</p>
      <p v-else class="paper-abstract paper-abstract-missing">该来源暂未提供摘要。</p>
      <details v-if="hasOriginalAbstract(p)" class="paper-original">
        <summary>查看原始摘要</summary>
        <p>{{ p.abstract }}</p>
      </details>

      <div class="paper-meta">
        <div class="meta-row">
          <span class="meta-label">作者</span>
          <span class="meta-value meta-authors" :title="authorsText(p)">{{ authorsText(p) }}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">发布时间</span>
          <span class="meta-value">{{ publishText(p) }}</span>
        </div>
      </div>

      <!-- 已收藏的论文：展示自定义标签 + 打标签入口 -->
      <div v-if="store.isFavInAny(p.id)" class="paper-tags">
        <el-tag
          v-for="t in (store.paperTags[p.id] ?? [])"
          :key="t"
          size="small"
          type="primary"
          effect="plain"
          closable
          class="ptag"
          @close="store.removeTag(p.id, t)"
        >{{ t }}</el-tag>
        <el-button size="small" text bg class="tag-add" @click="addTagFor(p)">＋ 标签</el-button>
      </div>

      <div class="paper-foot">
        <a
          v-if="p.url"
          class="paper-link"
          :href="p.url"
          target="_blank"
          rel="noopener"
          @click="store.markViewed(p)"
        >查看原文 ↗</a>
        <span v-else class="paper-nolink">暂无原文链接</span>
      </div>
    </el-card>
  </div>

  <!-- 星标弹窗：选择把论文收藏到哪个收藏夹（可跨多个；可取消） -->
  <el-dialog
    v-model="favDialogVisible"
    title="选择收藏夹"
    width="360px"
    align-center
    append-to-body
  >
    <div v-if="favTarget" class="fav-space-list">
      <div class="fav-space-target" :title="favTarget.title">{{ favTarget.title }}</div>
      <el-button
        class="fav-space-create"
        size="small"
        plain
        @click="createSpaceAndAdd"
      >＋ 新建收藏夹</el-button>
      <div
        v-for="s in store.spaces"
        :key="s.id"
        class="fav-space-row"
      >
        <span class="fav-space-name">{{ s.name }}</span>
        <el-button
          size="small"
          :type="favTargetIn.includes(s.id) ? 'warning' : 'default'"
          :plain="!favTargetIn.includes(s.id)"
          @click="toggleFavSpace(s.id)"
        >{{ favTargetIn.includes(s.id) ? '已收藏 ✓' : '收藏到此处' }}</el-button>
      </div>
    </div>
    <template #footer>
      <el-button
        v-if="favTargetIn.length"
        type="danger"
        plain
        size="small"
        @click="cancelAllFav"
      >取消全部收藏</el-button>
      <el-button size="small" type="primary" @click="favDialogVisible = false">完成</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.paper-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
  align-items: stretch;
}
.paper-card {
  height: 100%;
}
.paper-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.paper-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.paper-title {
  flex: 1 1 auto;
  min-width: 0;
}
.paper-title-original {
  margin-top: 4px;
  color: #8a94a6;
  font-size: 11.5px;
  line-height: 1.4;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.paper-original {
  margin-top: 6px;
  color: #8a94a6;
  font-size: 11.5px;
}
.paper-original summary {
  cursor: pointer;
}
.paper-original p {
  margin: 6px 0 0;
  line-height: 1.5;
}
.paper-title a {
  color: var(--el-color-primary);
  font-weight: 600;
  text-decoration: none;
  font-size: 14.5px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.paper-title a:hover {
  text-decoration: underline;
}
.paper-title-text {
  font-weight: 600;
  color: #1f2329;
  font-size: 14.5px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.fav-btn {
  flex: 0 0 auto;
}
.paper-abstract {
  margin: 10px 0 0;
  color: #444;
  font-size: 13px;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.paper-meta {
  margin-top: auto;
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12.5px;
}
.meta-row {
  display: flex;
  gap: 6px;
  align-items: baseline;
}
.meta-label {
  flex: 0 0 auto;
  color: #9aa3b2;
}
.meta-value {
  min-width: 0;
}
.meta-authors {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.paper-tags {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.ptag {
  user-select: none;
}
.tag-add {
  padding: 0 6px;
  height: 22px;
  font-size: 12px;
}
.paper-foot {
  margin-top: 10px;
}
.paper-link {
  font-size: 13px;
  color: var(--el-color-primary);
  text-decoration: none;
  font-weight: 500;
}
.paper-link:hover {
  text-decoration: underline;
}
.paper-nolink {
  font-size: 13px;
  color: #b0b6be;
}
/* 星标弹窗：收藏夹列表 */
.fav-space-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.fav-space-target {
  font-size: 13px;
  color: #1f2329;
  font-weight: 600;
  line-height: 1.4;
  max-height: 40px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  margin-bottom: 4px;
  padding-bottom: 8px;
  border-bottom: 1px solid #eef0f2;
}
.fav-space-create {
  justify-content: flex-start;
  padding-left: 6px;
  margin-bottom: 4px;
  width: auto;
  font-size: 12.5px;
}
.fav-space-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 4px 2px;
}
.fav-space-name {
  font-size: 13.5px;
  color: #3a4256;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
