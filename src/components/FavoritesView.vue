<script setup lang="ts">
import { useKpStore } from '../stores/knowledgeParty'
import PaperList from './PaperList.vue'

const store = useKpStore()
</script>

<template>
  <div class="favorites-view">
    <div class="fav-header">
      <span>收藏的文献</span>
      <el-tag round type="info">{{ store.favoriteList.length }}</el-tag>
    </div>

    <PaperList v-if="store.favoriteList.length" :papers="store.favoriteList" />

    <el-empty
      v-else
      description="还没有收藏的文献，去「搜索」里点击星标收藏吧"
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
  font-size: 18px;
  font-weight: 600;
  color: #1f2329;
  margin-bottom: 16px;
}
</style>
