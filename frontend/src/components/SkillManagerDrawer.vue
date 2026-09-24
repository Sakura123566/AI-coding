<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listSkills,
  createSkill,
  updateSkill,
  deleteSkill,
  type Skill,
  type SkillInput
} from '../services/skills'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const visible = ref(props.modelValue)
watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
    if (v) load()
  }
)
watch(visible, (v) => emit('update:modelValue', v))

const loading = ref(false)
const saving = ref(false)
const skills = ref<Skill[]>([])

// token 取自 localStorage（与 user store 同 key），避免额外依赖注入
function token(): string {
  try {
    const raw = localStorage.getItem('kp-user-v2')
    if (raw) return JSON.parse(raw).token ?? ''
  } catch {
    /* ignore */
  }
  return ''
}

async function load() {
  loading.value = true
  try {
    skills.value = await listSkills(token())
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载技能失败')
  } finally {
    loading.value = false
  }
}

// —— 新增 / 编辑对话框 ——
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive<{
  name: string
  description: string
  instruction: string
  enabled: boolean
  triggersText: string
}>({
  name: '',
  description: '',
  instruction: '',
  enabled: true,
  triggersText: ''
})

function openAdd() {
  editingId.value = null
  form.name = ''
  form.description = ''
  form.instruction = ''
  form.enabled = true
  form.triggersText = ''
  dialogVisible.value = true
}

function openEdit(s: Skill) {
  editingId.value = s.id
  form.name = s.name
  form.description = s.description
  form.instruction = s.instruction
  form.enabled = s.enabled
  form.triggersText = s.triggers.join('，')
  dialogVisible.value = true
}

function parseTriggers(text: string): string[] {
  return text
    .split(/[,，\s]+/)
    .map((t) => t.trim())
    .filter(Boolean)
}

async function submitForm() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写技能名称')
    return
  }
  if (!form.instruction.trim()) {
    ElMessage.warning('请填写执行指令（instruction）')
    return
  }
  saving.value = true
  const payload: SkillInput = {
    name: form.name.trim(),
    description: form.description.trim(),
    instruction: form.instruction.trim(),
    triggers: parseTriggers(form.triggersText),
    enabled: form.enabled
  }
  try {
    if (editingId.value == null) {
      await createSkill(token(), payload)
      ElMessage.success('技能已新增')
    } else {
      await updateSkill(token(), editingId.value, payload)
      ElMessage.success('技能已更新')
    }
    dialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(s: Skill, val: boolean) {
  try {
    await updateSkill(token(), s.id, { enabled: val })
    s.enabled = val
    ElMessage.success(val ? '已启用' : '已停用')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败')
    s.enabled = !val // 回滚开关
  }
}

async function remove(s: Skill) {
  try {
    await ElMessageBox.confirm(`确定删除技能「${s.name}」吗？`, '删除技能', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deleteSkill(token(), s.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败')
  }
}
</script>

<template>
  <el-drawer v-model="visible" title="技能管理" direction="ltr" size="460px">
    <div v-loading="loading" class="sm">
      <div class="sm-head">
        <span class="sm-count">共 {{ skills.length }} 个技能</span>
        <el-button type="primary" size="small" @click="openAdd">+ 新增技能</el-button>
      </div>

      <el-empty v-if="!skills.length" description="还没有技能，点右上角新增一个吧" />

      <div v-for="s in skills" :key="s.id" class="sm-card">
        <div class="sm-card-head">
          <span class="sm-name">{{ s.name }}</span>
          <el-switch
            :model-value="s.enabled"
            @change="(v: any) => toggleEnabled(s, !!v)"
            active-text="启用"
            inactive-text="停用"
            inline-prompt
          />
        </div>
        <div v-if="s.description" class="sm-desc">{{ s.description }}</div>
        <div class="sm-instruction">
          <span class="sm-label">指令</span>{{ s.instruction }}
        </div>
        <div v-if="s.triggers.length" class="sm-triggers">
          <el-tag v-for="t in s.triggers" :key="t" size="small" effect="plain" class="sm-tag">
            {{ t }}
          </el-tag>
        </div>
        <div class="sm-actions">
          <el-button text size="small" @click="openEdit(s)">编辑</el-button>
          <el-button text size="small" type="danger" @click="remove(s)">删除</el-button>
        </div>
      </div>
    </div>

    <!-- 新增 / 编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId == null ? '新增技能' : '编辑技能'"
      width="440px"
      append-to-body
    >
      <el-form label-position="top">
        <el-form-item label="技能名称" required>
          <el-input v-model="form.name" maxlength="60" show-word-limit placeholder="例如：论文精读" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            maxlength="200"
            show-word-limit
            placeholder="一句话说明这个技能做什么"
          />
        </el-form-item>
        <el-form-item label="执行指令（instruction）" required>
          <el-input
            v-model="form.instruction"
            type="textarea"
            :rows="4"
            maxlength="2000"
            show-word-limit
            placeholder="描述智能体在该技能下应如何行动，例如：按「背景-方法-结果-局限」结构输出。"
          />
        </el-form-item>
        <el-form-item label="触发词（逗号或空格分隔）">
          <el-input
            v-model="form.triggersText"
            placeholder="例如：精读，论文解析，拆解"
          />
        </el-form-item>
        <el-form-item label="是否启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </el-drawer>
</template>

<style scoped>
.sm {
  display: flex;
  flex-direction: column;
}
.sm-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.sm-count {
  font-size: 13px;
  color: #9aa0a6;
}
.sm-card {
  border: 1px solid #eef0f2;
  border-radius: 12px;
  padding: 12px 14px;
  margin-bottom: 12px;
  background: #fff;
}
.sm-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.sm-name {
  font-size: 15px;
  font-weight: 600;
  color: #1f2329;
}
.sm-desc {
  font-size: 13px;
  color: #5a6b8c;
  margin-bottom: 6px;
}
.sm-instruction {
  font-size: 13px;
  color: #333;
  line-height: 1.6;
  background: #f7f8fa;
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
}
.sm-label {
  display: inline-block;
  font-size: 11px;
  color: #9aa0a6;
  margin-right: 6px;
}
.sm-triggers {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.sm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}
</style>
