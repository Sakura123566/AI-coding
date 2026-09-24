<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '../stores/user'
import { IDENTITY_PRESETS, identityLabel, type ProfileUpdate } from '../types/user'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const userStore = useUserStore()
const visible = ref(props.modelValue)

watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
    if (v) userStore.fetchProfile() // 打开即拉取最新用户 + 画像（后端就绪后为真实数据）
  }
)
watch(visible, (v) => emit('update:modelValue', v))

const user = computed(() => userStore.user)
const portrait = computed(() => userStore.portrait)

function formatDate(s?: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  if (isNaN(d.getTime())) return '—'
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

// —— 完善资料编辑 ——
const editing = ref(false)
const saving = ref(false)
const editForm = reactive({
  display_name: '',
  real_name: '',
  age: '' as string,
  identity: ''
})

function openEdit() {
  const u = user.value
  if (!u) return
  editForm.display_name = u.display_name || ''
  editForm.real_name = u.real_name || ''
  editForm.age = u.age != null ? String(u.age) : ''
  editForm.identity = u.identity || ''
  editing.value = true
}

async function saveEdit() {
  saving.value = true
  try {
    const patch: ProfileUpdate = {
      display_name: editForm.display_name || undefined,
      real_name: editForm.real_name || undefined,
      age: editForm.age ? Number(editForm.age) : undefined,
      identity: editForm.identity || undefined
    }
    await userStore.saveProfile(patch)
    ElMessage.success('资料已保存')
    editing.value = false
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

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
  <el-drawer v-model="visible" title="我的资料" direction="ltr" size="380px">
    <div v-if="user" class="profile">
      <div class="pf-head">
        <div class="pf-avatar">{{ (user.display_name || user.username || '?').trim().charAt(0).toUpperCase() }}</div>
        <div class="pf-id">
          <div class="pf-name">{{ user.display_name || user.username }}</div>
          <el-tag size="small" type="info">{{ identityLabel(user.identity) }}</el-tag>
        </div>
        <el-button text type="primary" class="pf-edit-btn" @click="openEdit">完善资料</el-button>
      </div>

      <el-descriptions :column="1" border class="pf-desc">
        <el-descriptions-item label="用户名">{{ user.username }}</el-descriptions-item>
        <el-descriptions-item label="昵称">{{ user.display_name }}</el-descriptions-item>
        <el-descriptions-item label="真实姓名">{{ user.real_name || '—' }}</el-descriptions-item>
        <el-descriptions-item label="年龄">{{ user.age ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="身份">{{ identityLabel(user.identity) }}</el-descriptions-item>
        <el-descriptions-item label="注册于">{{ formatDate(user.created_at) }}</el-descriptions-item>
      </el-descriptions>

      <div class="pf-section-title">用户画像</div>
      <div v-if="portrait && portrait.has_enough_data" class="pf-portrait">
        <p v-if="portrait.profile.style.summary" class="pf-summary">{{ portrait.profile.style.summary }}</p>

        <div v-if="portrait.profile.domains.length" class="pf-block">
          <div class="pf-block-title">主要方向</div>
          <div class="pf-chips">
            <span v-for="d in portrait.profile.domains" :key="d.name" class="pf-chip">
              {{ d.name }} <em>{{ d.weight.toFixed(2) }}</em>
            </span>
          </div>
        </div>

        <div v-if="portrait.profile.interests.length" class="pf-block">
          <div class="pf-block-title">兴趣标签</div>
          <div class="pf-chips">
            <span v-for="it in portrait.profile.interests" :key="it.tag" class="pf-chip" :class="'trend-' + it.trend">
              {{ it.tag }}
              <i class="pf-trend">{{ it.trend === 'up' ? '↑' : it.trend === 'down' ? '↓' : '→' }}</i>
            </span>
          </div>
        </div>

        <div class="pf-block">
          <div class="pf-block-title">活跃度</div>
          <div class="pf-stats">
            <div class="pf-stat"><b>{{ portrait.profile.activity.total_searches }}</b><span>检索</span></div>
            <div class="pf-stat"><b>{{ portrait.profile.activity.total_messages }}</b><span>提问</span></div>
            <div class="pf-stat"><b>{{ portrait.profile.activity.active_days }}</b><span>活跃天</span></div>
          </div>
        </div>
      </div>
      <el-empty
        v-else-if="portrait"
        description="样本不足，多用几次检索后会自动生成你的画像"
        :image-size="80"
      />

      <div class="pf-footer">
        <el-button type="danger" plain @click="onLogout">退出登录</el-button>
      </div>
    </div>
    <el-empty v-else description="未登录" />

    <!-- 完善资料 -->
    <el-dialog v-model="editing" title="完善资料" width="360px" append-to-body>
      <el-form label-position="top">
        <el-form-item label="昵称">
          <el-input v-model="editForm.display_name" placeholder="昵称" />
        </el-form-item>
        <el-form-item label="真实姓名">
          <el-input v-model="editForm.real_name" placeholder="选填" />
        </el-form-item>
        <el-form-item label="年龄">
          <el-input v-model="editForm.age" type="number" placeholder="如 22" />
        </el-form-item>
        <el-form-item label="身份">
          <el-select v-model="editForm.identity" placeholder="选择身份" clearable style="width: 100%">
            <el-option v-for="p in IDENTITY_PRESETS" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editing = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
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
.pf-edit-btn {
  margin-left: auto;
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
.pf-portrait {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.pf-summary {
  font-size: 13px;
  line-height: 1.7;
  color: #5a6b8c;
  background: #f5f8ff;
  border: 1px solid #e6eeff;
  border-radius: 10px;
  padding: 10px 12px;
  margin: 0;
}
.pf-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pf-block-title {
  font-size: 13px;
  color: #6b7280;
  font-weight: 600;
}
.pf-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.pf-chip {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 999px;
  background: #eef2f7;
  color: #1f2329;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.pf-chip em {
  font-style: normal;
  color: #9aa0a6;
  font-size: 11px;
}
.pf-chip.trend-up {
  background: #e8f7ee;
  color: #1a7f47;
}
.pf-chip.trend-down {
  background: #fdecec;
  color: #c0392b;
}
.pf-chip.trend-flat {
  background: #eef2f7;
  color: #5a6b8c;
}
.pf-trend {
  font-style: normal;
  font-weight: 700;
}
.pf-stats {
  display: flex;
  gap: 10px;
}
.pf-stat {
  flex: 1;
  background: #f7f9fc;
  border-radius: 10px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.pf-stat b {
  font-size: 18px;
  color: #2b6cff;
}
.pf-stat span {
  font-size: 12px;
  color: #9aa0a6;
}
.pf-footer {
  margin-top: 8px;
}
</style>
