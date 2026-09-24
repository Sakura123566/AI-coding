<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDown, User } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'

defineProps<{ expanded: boolean }>()
const emit = defineEmits<{ (e: 'click'): void }>()

const userStore = useUserStore()

const isLoggedIn = computed(() => userStore.isLoggedIn)
const name = computed(() => userStore.user?.display_name ?? userStore.user?.username ?? '登录')
const initial = computed(() => (name.value ? name.value.trim().charAt(0).toUpperCase() : '?'))
const bg = computed(() => colorFromName(name.value))

// 由名字稳定生成头像底色
function colorFromName(s: string): string {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360
  return `hsl(${h} 65% 55%)`
}
</script>

<template>
  <div
    class="ua"
    :class="{ expanded: expanded, logged: isLoggedIn }"
    :title="isLoggedIn ? '查看我的资料' : '登录 / 注册'"
    @click="emit('click')"
  >
    <div class="ua-avatar" :style="{ background: isLoggedIn ? bg : '#c9ced6' }">
      <span v-if="isLoggedIn">{{ initial }}</span>
      <el-icon v-else><User /></el-icon>
    </div>
    <span v-if="expanded" class="ua-name">{{ name }}</span>
    <el-icon v-if="expanded && isLoggedIn" class="ua-caret"><ArrowDown /></el-icon>
  </div>
</template>

<style scoped>
.ua {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-radius: 10px;
  cursor: pointer;
  color: #555;
  transition: background 0.15s;
  width: 100%;
  box-sizing: border-box;
}
.ua:hover {
  background: #eef2f7;
}
.ua-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 600;
  font-size: 15px;
  flex: 0 0 auto;
}
.ua-avatar .el-icon {
  font-size: 18px;
  color: #fff;
}
.ua-name {
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ua-caret {
  font-size: 12px;
  color: #9aa0a6;
  margin-left: auto;
}
.ua.expanded {
  justify-content: flex-start;
}
</style>
