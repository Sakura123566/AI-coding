<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '../stores/user'
import { IDENTITY_LABELS } from '../types/user'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const userStore = useUserStore()
const visible = ref(props.modelValue)

watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
    if (v) userStore.fetchProfile() // 打开即拉取最新画像（后端就绪后为真实数据）
  }
)
watch(visible, (v) => emit('update:modelValue', v))

const user = computed(() => userStore.user)
const profile = computed(() => user.value?.profile)
const identityLabel = computed(() =>
  user.value?.identity ? IDENTITY_LABELS[user.value.identity] : '—'
)

async function onLogout() {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '退出登录', {
      type: 'warning',
      confirmButtonText: '退出',
      cancelButtonText: '取消'
    })
    userStore.logout()
    ElMessage.success('已退出登录')
    visible.value = false
  } catch {
    /* 用户取消 */
  }
}
</script>

<template>
  <el-drawer v-model="visible" title="我的资料" direction="ltr" size="360px">
    <div v-if="user" class="profile">
      <div class="pf-head">
        <div class="pf-avatar">{{ (user.name || '?').trim().charAt(0).toUpperCase() }}</div>
        <div class="pf-id">
          <div class="pf-name">{{ user.name }}</div>
          <el-tag size="small" type="info">{{ identityLabel }}</el-tag>
        </div>
      </div>

      <el-descriptions :column="1" border class="pf-desc">
        <el-descriptions-item label="姓名">{{ user.name }}</el-descriptions-item>
        <el-descriptions-item label="年龄">{{ user.age ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="身份">{{ identityLabel }}</el-descriptions-item>
        <el-descriptions-item label="邮箱">{{ user.email }}</el-descriptions-item>
      </el-descriptions>

      <div class="pf-section-title">用户画像</div>
      <div v-if="profile?.summary" class="pf-summary">{{ profile.summary }}</div>

      <div v-if="profile?.facets?.length" class="pf-facets">
        <div v-for="f in profile.facets" :key="f.label" class="pf-facet">
          <span class="pf-facet-label">{{ f.label }}</span>
          <span class="pf-facet-value">{{ f.value }}</span>
        </div>
      </div>

      <div v-if="profile?.tags?.length" class="pf-tags">
        <el-tag v-for="t in profile.tags" :key="t" size="small" effect="plain" class="pf-tag">{{ t }}</el-tag>
      </div>

      <div class="pf-footer">
        <el-button type="danger" plain @click="onLogout">退出登录</el-button>
      </div>
    </div>
    <el-empty v-else description="未登录" />
  </el-drawer>
</template>

<style scoped>
.profile {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.pf-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.pf-avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, #2b6cff 0%, #6a5cff 100%);
  color: #fff;
  font-size: 22px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
}
.pf-id {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pf-name {
  font-size: 18px;
  font-weight: 700;
  color: #1f2329;
}
.pf-desc {
  margin-top: 4px;
}
.pf-section-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2329;
  margin-top: 4px;
}
.pf-summary {
  font-size: 13px;
  line-height: 1.7;
  color: #5a6b8c;
  background: #f5f8ff;
  border: 1px solid #e6eeff;
  border-radius: 10px;
  padding: 10px 12px;
}
.pf-facets {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pf-facet {
  display: flex;
  gap: 10px;
  font-size: 13px;
}
.pf-facet-label {
  flex: 0 0 76px;
  color: #9aa0a6;
}
.pf-facet-value {
  flex: 1;
  color: #1f2329;
}
.pf-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.pf-footer {
  margin-top: 8px;
}
</style>
