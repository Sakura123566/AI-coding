<script setup lang="ts">
import { Star, StarFilled } from '@element-plus/icons-vue'
import { useKpStore } from '../stores/knowledgeParty'
import type { Paper } from '../services/research'
import { ElMessage, ElMessageBox } from 'element-plus'

defineProps<{
  papers: Paper[]
}>()

const store = useKpStore()

function authorsText(p: Paper): string {
  if (!p.authors || p.authors.length === 0) return '作者未知'
  return p.authors.join(', ')
}
function publishText(p: Paper): string {
  return p.year ? `${p.year} 年` : '年份未知'
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
          >{{ p.title }}</a>
          <span v-else class="paper-title-text" :title="p.title">{{ p.title }}</span>
        </div>
        <el-button
          class="fav-btn"
          :type="store.isFavorite(p.id) ? 'warning' : 'info'"
          :plain="!store.isFavorite(p.id)"
          circle
          size="small"
          :title="store.isFavorite(p.id) ? '取消收藏' : '收藏'"
          @click="store.toggleFavorite(p)"
        >
          <el-icon>
            <component :is="store.isFavorite(p.id) ? StarFilled : Star" />
          </el-icon>
        </el-button>
      </div>

      <p class="paper-abstract">{{ p.abstract || '暂无摘要' }}</p>

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
      <div v-if="store.isFavorite(p.id)" class="paper-tags">
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
</style>
