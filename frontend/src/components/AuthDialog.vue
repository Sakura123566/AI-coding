<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { isDemoMode } from '../config/runtime'
import { useUserStore } from '../stores/user'
import { IDENTITY_PRESETS, type ProfileUpdate } from '../types/user'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'success'): void
}>()

const userStore = useUserStore()

const visible = ref(props.modelValue)
watch(
  () => props.modelValue,
  (v) => (visible.value = v)
)
watch(visible, (v) => emit('update:modelValue', v))

const tab = ref<'login' | 'register'>('login')

const loginForm = reactive({ username: '', password: '' })
const regForm = reactive({
  username: '',
  password: '',
  display_name: '',
  age: '' as string,
  identity: ''
})

const submitting = computed(() => userStore.loading)

async function enterDemo() {
  await userStore.login({ username: 'demo', password: 'demo123' })
  if (userStore.isLoggedIn) {
    ElMessage.success('已进入演示模式')
    emit('success')
    visible.value = false
  }
}
async function onSubmit() {
  if (tab.value === 'login') {
    if (!loginForm.username || !loginForm.password) {
      ElMessage.warning('请输入用户名和密码')
      return
    }
    await userStore.login({ ...loginForm })
  } else {
    if (!regForm.username || !regForm.password) {
      ElMessage.warning('请填写用户名和密码')
      return
    }
    // 后端 register 只收 username/password/display_name；
    // age/identity 走注册后的 saveProfile（PATCH /api/auth/me）。
    await userStore.register({
      username: regForm.username,
      password: regForm.password,
      display_name: regForm.display_name || undefined
    })
    if (userStore.isLoggedIn) {
      const extra: ProfileUpdate = {}
      if (regForm.age) extra.age = Number(regForm.age)
      if (regForm.identity) extra.identity = regForm.identity
      if (extra.age !== undefined || extra.identity !== undefined) {
        try {
          await userStore.saveProfile(extra)
        } catch {
          // 资料补全是尽力而为，不阻塞注册成功
        }
      }
    }
  }

  if (userStore.isLoggedIn) {
    ElMessage.success('欢迎来到知识派对 🎉')
    emit('success')
    visible.value = false
  } else if (userStore.error) {
    ElMessage.error(userStore.error)
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="tab === 'login' ? '登录' : '注册'" width="400px" align-center>
    <el-tabs v-model="tab" class="auth-tabs">
      <el-tab-pane label="登录" name="login" />
      <el-tab-pane label="注册" name="register" />
    </el-tabs>

    <el-alert
      v-if="isDemoMode"
      class="demo-auth-note"
      type="warning"
      :closable="false"
      show-icon
      title="演示账号仅保存在当前浏览器，不会创建真实账号。"
    />
    <el-form label-position="top" @submit.prevent="onSubmit">
      <template v-if="tab === 'login'">
        <el-form-item label="用户名">
          <el-input v-model="loginForm.username" placeholder="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="loginForm.password"
            type="password"
            show-password
            placeholder="请输入密码"
            :prefix-icon="Lock"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
      </template>

      <template v-else>
        <el-form-item label="用户名">
          <el-input v-model="regForm.username" placeholder="2-32 个字符" :prefix-icon="User" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="regForm.password"
            type="password"
            show-password
            placeholder="至少 6 位"
            :prefix-icon="Lock"
          />
        </el-form-item>
        <el-form-item label="昵称（可选）">
          <el-input v-model="regForm.display_name" placeholder="不填则默认用用户名" />
        </el-form-item>
        <el-form-item label="年龄（可选）">
          <el-input v-model="regForm.age" type="number" placeholder="如 22" />
        </el-form-item>
        <el-form-item label="身份（可选）">
          <el-select v-model="regForm.identity" placeholder="选择身份" clearable style="width: 100%">
            <el-option
              v-for="p in IDENTITY_PRESETS"
              :key="p.value"
              :label="p.label"
              :value="p.value"
            />
          </el-select>
        </el-form-item>
      </template>
    </el-form>

    <template #footer>
      <el-button v-if="isDemoMode" @click="enterDemo">一键进入演示</el-button>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="onSubmit">
        {{ tab === 'login' ? '登录' : '注册并登录' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.auth-tabs {
  margin-bottom: 4px;
}
.demo-auth-note {
  margin-bottom: 14px;
}
</style>
