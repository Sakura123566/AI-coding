<script setup lang="ts">
import { computed, ref } from 'vue'
import { useKpStore } from '../stores/knowledgeParty'
import PaperList from './PaperList.vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const store = useKpStore()
const activeTag = ref<string | null>(null)

// 当前收藏夹内出现的标签（筛选条只展示与当前收藏相关的标签）
const visibleTags = computed(() => {
  const set = new Set<string>()
  for (const p of store.favoriteList) {
    for (const t of store.paperTags[p.id] ?? []) set.add(t)
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b, 'zh'))
})

// 按标签筛选（仅当前收藏夹内）
const displayed = computed(() => {
  if (!activeTag.value) return store.favoriteList
  return store.favoriteList.filter((p) => (store.paperTags[p.id] ?? []).includes(activeTag.value!))
})

function switchCollection(id: string) {
  store.switchSpace(id)
  activeTag.value = null
}

async function newCollection() {
  try {
    const { value } = await ElMessageBox.prompt('给新收藏夹起个名字', '新建收藏夹', {
      inputPattern: /\S+/,
      inputErrorMessage: '名字不能为空',
      confirmButtonText: '创建',
      cancelButtonText: '取消'
    })
    if (value && value.trim()) {
      store.addSpace(value.trim())
      ElMessage.success('已新建收藏夹')
    }
  } catch {
    /* 取消 */
  }
}
</script>

<template>
  <div class="favorites-view">
    <div class="fav-header">
      <span class="fav-title">收藏的文献</span>
      <el-select
        :model-value="store.currentSpaceId"
        @change="switchCollection"
        size="small"
        class="coll-select"
        placeholder="选择收藏夹"
      >
        <el-option v-for="s in store.spaces" :key="s.id" :label="s.name" :value="s.id" />
      </el-select>
      <el-button size="small" @click="newCollection">＋ 新建收藏夹</el-button>
      <span class="auto-sort">
        <el-tooltip content="开启后，点星标会把文献自动收进以当前主题命名的收藏夹（没有则自动创建）" placement="top">
          <span class="auto-sort-label">按主题自动归类</span>
        </el-tooltip>
        <el-switch
          :model-value="store.autoSortByTopic"
          @change="store.setAutoSortByTopic"
          size="small"
        />
      </span>
      <el-tag round type="info" class="coll-count">{{ displayed.length }}</el-tag>
    </div>

    <div v-if="visibleTags.length" class="tag-filter">
      <el-tag
        :type="activeTag === null ? 'primary' : 'info'"
        effect="plain"
        class="tag-chip"
        @click="activeTag = null"
      >全部</el-tag>
      <el-tag
        v-for="t in visibleTags"
        :key="t"
        :type="activeTag === t ? 'primary' : 'info'"
        effect="plain"
        class="tag-chip"
        @click="activeTag = activeTag === t ? null : t"
      >{{ t }}</el-tag>
    </div>

    <PaperList v-if="displayed.length" :papers="displayed" />

    <el-empty
      v-else
      :description="store.favoriteList.length ? '该标签下没有收藏' : '还没有收藏的文献，去「搜索」里点击星标收藏吧'"
      :image-size="90"
    />
  </div>
</template>

<style scoped>
.favorites-view {
  max-width: 1000px;
}
.fav-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.fav-title {
  font-size: 18px;
  font-weight: 600;
  color: #1f2329;
}
.coll-select {
  width: 160px;
}
.coll-count {
  margin-left: auto;
}
.auto-sort {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: 4px;
  color: #6b7280;
  font-size: 12.5px;
  white-space: nowrap;
}
.auto-sort-label {
  user-select: none;
}
.tag-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}
.tag-chip {
  cursor: pointer;
  user-select: none;
}
</style>
