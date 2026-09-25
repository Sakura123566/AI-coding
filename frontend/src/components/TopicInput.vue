<script setup lang="ts">
defineProps<{
  loading: boolean
  modelValue: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'submit'): void
}>()

function onSearch() {
  emit('submit')
}
</script>

<template>
  <div class="topic-input">
    <el-input
      :model-value="modelValue"
      type="textarea"
      :rows="3"
      placeholder="想请哪些知识点来这场派对？例如：大语言模型在代码生成中的评测方法"
      :disabled="loading"
      @update:model-value="emit('update:modelValue', $event)"
      @keydown.enter.exact.prevent="onSearch"
      @keydown.ctrl.enter.prevent="onSearch"
      @keydown.meta.enter.prevent="onSearch"
    />
    <div class="actions">
      <el-button
        type="primary"
        :loading="loading"
        :disabled="loading"
        @click="onSearch"
      >
        生成报告
      </el-button>
      <span class="hint">Enter 直接发请柬，Shift + Enter 换行</span>
    </div>
  </div>
</template>

<style scoped>
.topic-input {
  width: 100%;
  max-width: 760px;
}
.actions {
  margin-top: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.hint {
  font-size: 12px;
  color: #9aa0a6;
}
</style>
