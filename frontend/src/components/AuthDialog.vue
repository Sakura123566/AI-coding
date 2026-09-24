<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Lock, Message } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'
import { IDENTITY_LABELS, type UserIdentity } from '../types/user'

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

const loginForm = reactive({ email: '', password: '' })
const regForm = reactive({
  email: '',
  password: '',
  name: '',
  age: '' as string,
  identity: '' as UserIdentity | ''
})

const submitting = computed(() => userStore.loading)

async function onSubmit() {
  if (tab.value === 'login') {
    if (!loginForm.email || !loginForm.password) {
      ElMessage.warning('请输入邮箱和密码')
      return
    }
    await userStore.login({ ...loginForm })
  } else {
    if (!regForm.email || !regForm.password || !regForm.name) {
      ElMessage.warning('请填写邮箱、密码和姓名')
      return
    }
    await userStore.register({
      email: regForm.email,
      password: regForm.password,
      name: regForm.name,
      age: regForm.age ? Number(regForm.age) : undefined,
      identity: regForm.identity || undefined
    })
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

    <el-form label-position="top" @submit.prevent="onSubmit">
      <template v-if="tab === 'login'">
        <el-form-item label="邮箱">
          <el-input v-model="loginForm.email" placeholder="you@example.com" :prefix-icon="Message" />
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
        <el-form-item label="姓名">
          <el-input v-model="regForm.name" placeholder="你的姓名" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="regForm.email" placeholder="you@example.com" :prefix-icon="Message" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="regForm.password"
            type="password"
            show-password
            placeholder="设置密码"
            :prefix-icon="Lock"
          />
        </el-form-item>
        <el-form-item label="年龄（可选）">
          <el-input v-model="regForm.age" type="number" placeholder="如 22" />
        </el-form-item>
        <el-form-item label="身份（可选）">
          <el-select v-model="regForm.identity" placeholder="选择身份" clearable style="width: 100%">
            <el-option
              v-for="(label, key) in IDENTITY_LABELS"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
        </el-form-item>
      </template>
    </el-form>

    <template #footer>
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
</style>
