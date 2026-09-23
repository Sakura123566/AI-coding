<script setup lang="ts">
import { formatRelative } from '../utils/time'
import type { HistoryEntry } from '../stores/knowledgeParty'

defineProps<{
  history: HistoryEntry[]
  title?: string
  limit?: number
}>()

const emit = defineEmits<{
  (e: 'select', topic: string): void
}>()

function list(history: HistoryEntry[], limit?: number): HistoryEntry[] {
  return limit && limit > 0 ? history.slice(0, limit) : history
}
</script>

<template>
  <div class="history">
    <div class="block-title">{{ title ?? '历史' }}</div>
    <el-empty v-if="history.length === 0" description="暂无记录" :image-size="48" />
    <ul v-else class="history-list">
      <li
        v-for="(h, i) in list(history, limit)"
        :key="i"
        :title="h.q"
        @click="emit('select', h.q)"
      >
        <span class="h-q">{{ h.q }}</span>
        <span class="h-time">{{ formatRelative(h.at) }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.history {
  margin-top: 22px;
}
.block-title {
  font-size: 12px;
  color: #9aa0a6;
  margin-bottom: 8px;
  letter-spacing: 1px;
}
.history-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 220px;
  overflow-y: auto;
}
.history-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f2f3f5;
  font-size: 13px;
  color: #333;
  cursor: pointer;
}
.h-q {
  flex: 1 1 auto;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.h-time {
  flex: 0 0 auto;
  font-size: 11px;
  color: #9aa0a6;
}
.history-list li:hover {
  background: #e8f0fe;
  color: var(--el-color-primary);
}
.history-list li:hover .h-time {
  color: var(--el-color-primary);
}
</style>
