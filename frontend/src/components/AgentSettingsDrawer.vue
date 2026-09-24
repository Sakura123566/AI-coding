<script setup lang="ts">
import { reactive, ref, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../stores/user'
import { useAgentSettings } from '../composables/useAgentSettings'
import {
  AGENT_PERSONALITY_LABELS,
  AGENT_TONE_LABELS,
  AGENT_DETAIL_LABELS,
  AGENT_LANGUAGE_LABELS,
  type AgentPersonality,
  type AgentTone,
  type AgentDetailLevel,
  type AgentLanguage,
  type AgentSettings
} from '../types/user'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const userStore = useUserStore()
const agent = useAgentSettings()
const visible = ref(props.modelValue)

watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
    if (v) loadSettings()
  }
)
watch(visible, (v) => emit('update:modelValue', v))

const loading = ref(false)
const saving = ref(false)
const form = reactive<AgentSettings>({
  personality: 'rigorous_warm',
  tone: 'professional',
  detail_level: 'balanced',
  language: 'zh-CN',
  voice_enabled: true,
  voice_auto_play: false,
  voice_name: 'xiaoyan',
  voice_rate: 1.0,
  voice_pitch: 1.0,
  custom_instructions: '',
  agent_address_name: ''
})

const personalityOptions = (Object.keys(AGENT_PERSONALITY_LABELS) as AgentPersonality[]).map(
  (v) => ({ value: v, label: AGENT_PERSONALITY_LABELS[v] })
)
const toneOptions = (Object.keys(AGENT_TONE_LABELS) as AgentTone[]).map((v) => ({
  value: v,
  label: AGENT_TONE_LABELS[v]
}))
const detailOptions = (Object.keys(AGENT_DETAIL_LABELS) as AgentDetailLevel[]).map((v) => ({
  value: v,
  label: AGENT_DETAIL_LABELS[v]
}))
const languageOptions = (Object.keys(AGENT_LANGUAGE_LABELS) as AgentLanguage[]).map((v) => ({
  value: v,
  label: AGENT_LANGUAGE_LABELS[v]
}))

// 常用语音音色（mock/前端可选，后端以 voice_name 字符串为准）
const voiceOptions = [
  { value: 'xiaoyan', label: '晓妍（女声·温柔）' },
  { value: 'xiaoyu', label: '晓宇（男声·沉稳）' },
  { value: 'xiaomeng', label: '晓萌（女声·活泼）' },
  { value: 'laochen', label: '老陈（男声·磁性）' }
]

const customLen = computed(() => form.custom_instructions.length)
const customOver = computed(() => customLen.value > 2000)

async function loadSettings() {
  if (!userStore.token) return
  loading.value = true
  try {
    const s = await agent.load(userStore.token)
    if (s) Object.assign(form, s)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '读取智能体设置失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!userStore.token) return
  if (customOver.value) {
    ElMessage.warning('自定义指令不能超过 2000 字')
    return
  }
  saving.value = true
  try {
    const saved = await agent.save(userStore.token, { ...form })
    if (saved) Object.assign(form, saved)
    ElMessage.success('智能体设置已保存')
    visible.value = false
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-drawer v-model="visible" title="智能体设置" direction="ltr" size="400px">
    <div v-loading="loading" class="as">
      <el-form label-position="top">
        <el-divider content-position="left">性格与语气</el-divider>

        <el-form-item label="智能体性格">
          <el-select v-model="form.personality" style="width: 100%">
            <el-option
              v-for="o in personalityOptions"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="语气">
          <el-select v-model="form.tone" style="width: 100%">
            <el-option v-for="o in toneOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>

        <el-form-item label="回答详尽程度">
          <el-radio-group v-model="form.detail_level">
            <el-radio-button v-for="o in detailOptions" :key="o.value" :value="o.value">
              {{ o.label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="语言偏好">
          <el-radio-group v-model="form.language">
            <el-radio-button v-for="o in languageOptions" :key="o.value" :value="o.value">
              {{ o.label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-divider content-position="left">语音设置</el-divider>

        <el-form-item label="启用语音播报">
          <el-switch v-model="form.voice_enabled" />
        </el-form-item>

        <template v-if="form.voice_enabled">
          <el-form-item label="自动播放">
            <el-switch v-model="form.voice_auto_play" />
            <span class="as-hint">开启后智能体回答将自动朗读</span>
          </el-form-item>

          <el-form-item label="语音音色">
            <el-select v-model="form.voice_name" style="width: 100%">
              <el-option
                v-for="o in voiceOptions"
                :key="o.value"
                :label="o.label"
                :value="o.value"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="语速">
            <el-slider
              v-model="form.voice_rate"
              :min="0.5"
              :max="2.0"
              :step="0.1"
              show-input
            />
          </el-form-item>

          <el-form-item label="音调">
            <el-slider
              v-model="form.voice_pitch"
              :min="0.5"
              :max="2.0"
              :step="0.1"
              show-input
            />
          </el-form-item>
        </template>

        <el-divider content-position="left">称呼与个性化</el-divider>

        <el-form-item label="希望被如何称呼">
          <el-input
            v-model="form.agent_address_name"
            maxlength="20"
            show-word-limit
            placeholder="例如：小明（留空则默认用你的昵称）"
          />
          <span class="as-hint">智能体会在对话里用这个称呼你；留空时回退到你的资料昵称。</span>
        </el-form-item>

        <el-divider content-position="left">自定义指令</el-divider>

        <el-form-item label="自定义指令（≤ 2000 字）">
          <el-input
            v-model="form.custom_instructions"
            type="textarea"
            :rows="5"
            maxlength="2000"
            show-word-limit
            placeholder="例如：回答时多用比喻，少用术语；优先推荐近三年的综述。"
          />
          <span v-if="customOver" class="as-over">已超出 2000 字限制</span>
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-drawer>
</template>

<style scoped>
.as {
  display: flex;
  flex-direction: column;
}
.as-hint {
  margin-left: 10px;
  font-size: 12px;
  color: #9aa0a6;
}
.as-over {
  color: #c0392b;
  font-size: 12px;
}
</style>
