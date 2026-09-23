<script setup lang="ts">
import { ref } from 'vue'
import History from './History.vue'
import { useKpStore } from '../stores/knowledgeParty'
import { useResearch } from '../composables/useResearch'
import { formatRelative } from '../utils/time'
import type { ViewedEntry } from '../stores/knowledgeParty'

const store = useKpStore()
const { topic, submit } = useResearch()

// 页面上方选择看哪种历史，默认「搜索记录」
const activeTab = ref<'search' | 'viewed'>('search')

function onSearchTopic(t: string) {
  store.setMode('search')
  topic.value = t
  submit()
}

function openPaper(p: ViewedEntry) {
  store.markViewed(p)
  if (p.url) window.open(p.url, '_blank', 'noopener')
}
</script>

<template>
  <div class="history-view">
    <el-tabs v-model="activeTab" class="hv-tabs">
      <el-tab-pane name="search">
        <template #label>
          搜索记录 <span class="hv-count">{{ store.currentHistory.length }}</span>
        </template>
        <History
          v-if="store.currentHistory.length"
          :history="store.currentHistory"
          title=""
          @select="onSearchTopic"
        />
        <el-empty v-else description="当前空间还没有搜索记录" :image-size="64" />
      </el-tab-pane>

      <el-tab-pane name="viewed">
        <template #label>
          观看过的文献 <span class="hv-count">{{ store.viewedList.length }}</span>
        </template>
        <el-empty
          v-if="store.viewedList.length === 0"
          description="还没有观看过的文献，去搜索后点开论文吧"
          :image-size="64"
        />
        <ul v-else class="viewed-list">
          <li v-for="p in store.viewedList" :key="p.id" @click="openPaper(p)">
            <div class="v-title">{{ p.title }}</div>
            <div class="v-meta">
              <span>{{ p.authors.slice(0, 3).join(', ') }}{{ p.authors.length > 3 ? ' 等' : '' }}</span>
              <span class="dot">·</span>
              <span>{{ p.source }}</span>
              <span class="dot">·</span>
              <span>{{ p.year }}</span>
              <span class="dot">·</span>
              <span class="v-time">{{ formatRelative(p.at) }}</span>
            </div>
          </li>
        </ul>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.history-view {
  max-width: 1000px;
}
.hv-tabs {
  --el-tabs-header-height: auto;
}
.hv-count {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 10px;
  background: #f2f3f5;
  color: #888;
  font-size: 12px;
  line-height: 20px;
  text-align: center;
  margin-left: 4px;
}
.viewed-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.viewed-list li {
  padding: 12px 14px;
  border-radius: 10px;
  background: #fafbfc;
  border: 1px solid #f0f1f3;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.viewed-list li:hover {
  background: #eef4ff;
  border-color: #d6e4ff;
}
.v-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2329;
  line-height: 1.5;
}
.v-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #888;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}
.v-time {
  color: #b0b6be;
}
.dot {
  color: #ccc;
}
</style>
