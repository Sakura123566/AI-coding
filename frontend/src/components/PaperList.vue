<script setup lang="ts">
import { Star, StarFilled } from '@element-plus/icons-vue'
import { useKpStore } from '../stores/knowledgeParty'
import type { Paper } from '../services/research'

defineProps<{
  papers: Paper[]
}>()

const store = useKpStore()
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
      <template #header>
        <div class="paper-head">
          <div class="paper-title">
            <a
              v-if="p.url"
              :href="p.url"
              target="_blank"
              rel="noopener"
              @click="store.markViewed(p)"
            >{{ p.title }}</a>
            <span v-else class="paper-title-text">{{ p.title }}</span>
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
      </template>
      <div class="paper-meta">
        <template v-if="p.authors.length">
          <span>{{ p.authors.join(', ') }}</span>
          <span class="dot">·</span>
        </template>
        <span v-if="p.source" class="source">来源：{{ p.source }}</span>
        <span v-if="p.source" class="dot">·</span>
        <span>{{ p.year || '年份未知' }}</span>
      </div>
      <p class="paper-abstract">{{ p.abstract || '暂无摘要' }}</p>
      <div class="paper-foot">
        <a
          v-if="p.url"
          class="paper-link"
          :href="p.url"
          target="_blank"
          rel="noopener"
          @click="store.markViewed(p)"
        >
          查看原文 ↗
        </a>
        <span v-else class="paper-nolink">暂无原文链接</span>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.paper-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.paper-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.paper-title {
  flex: 1 1 auto;
}
.paper-title a {
  color: var(--el-color-primary);
  font-weight: 600;
  text-decoration: none;
}
.paper-title a:hover {
  text-decoration: underline;
}
.paper-title-text {
  font-weight: 600;
  color: #1f2329;
}
.fav-btn {
  flex: 0 0 auto;
}
.paper-meta {
  color: #888;
  font-size: 13px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}
.source {
  color: #5a6b8c;
}
.paper-abstract {
  margin-top: 8px;
  color: #444;
  line-height: 1.6;
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
