<script setup lang="ts">
import { isDemoMode } from '../config/runtime'
</script>

<template>
  <div v-if="isDemoMode" class="demo-banner" role="status" aria-live="polite">
    <strong>演示模式</strong>
    <span>论文、报告、账号与知识图谱均为本地样例，不会访问真实后端。</span>
  </div>
</template>

<style scoped>
.demo-banner {
  position: fixed;
  top: 10px;
  left: 50%;
  z-index: 2000;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: calc(100vw - 32px);
  padding: 7px 13px;
  transform: translateX(-50%);
  border: 1px solid #f0c36d;
  border-radius: 999px;
  background: rgba(255, 249, 232, 0.96);
  color: #7a4f00;
  box-shadow: 0 5px 18px rgba(83, 58, 9, 0.12);
  font-size: 12px;
  line-height: 1.4;
  pointer-events: none;
}

.demo-banner strong {
  flex: 0 0 auto;
  font-weight: 700;
}

.demo-banner span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 720px) {
  .demo-banner {
    top: 6px;
    width: calc(100vw - 20px);
    border-radius: 12px;
    justify-content: center;
  }

  .demo-banner span {
    white-space: normal;
  }
}
</style>