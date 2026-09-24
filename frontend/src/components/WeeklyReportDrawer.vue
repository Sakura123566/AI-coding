<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Printer } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'
import { getWeeklyReport, downloadWeeklyReportPdf } from '../services/reports'
import type { WeeklyReport } from '../types/user'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const userStore = useUserStore()
const visible = ref(props.modelValue)

watch(
  () => props.modelValue,
  (v) => {
    visible.value = v
    if (v) loadReport()
  }
)
watch(visible, (v) => emit('update:modelValue', v))

const loading = ref(false)
const downloading = ref(false)
const report = ref<WeeklyReport | null>(null)

const summary = computed(() => {
  const r = report.value?.report as Record<string, any> | undefined
  return r?.summary ? String(r.summary) : ''
})
const highlights = computed(() => {
  const r = report.value?.report as Record<string, any> | undefined
  return Array.isArray(r?.highlights) ? (r!.highlights as any[]) : []
})
const metric = (key: string): string | number => {
  const r = report.value?.report as Record<string, any> | undefined
  return r?.[key] ?? '—'
}
const topKeywords = computed(() => {
  const r = report.value?.report as Record<string, any> | undefined
  return Array.isArray(r?.top_keywords) ? (r!.top_keywords as string[]) : []
})

async function loadReport() {
  if (!userStore.token) return
  loading.value = true
  try {
    report.value = await getWeeklyReport(userStore.token)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '读取周报失败')
  } finally {
    loading.value = false
  }
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function downloadJson() {
  if (!report.value) return
  const blob = new Blob([JSON.stringify(report.value, null, 2)], {
    type: 'application/json'
  })
  triggerDownload(blob, `weekly-report-${report.value.week_start}.json`)
}

async function downloadPdf() {
  if (!userStore.token) return
  downloading.value = true
  try {
    const blob = await downloadWeeklyReportPdf(userStore.token)
    const start = report.value?.week_start || 'now'
    triggerDownload(blob, `weekly-report-${start}.pdf`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : 'PDF 下载失败')
  } finally {
    downloading.value = false
  }
}
</script>

<template>
  <el-drawer v-model="visible" title="周报" direction="ltr" size="420px">
    <div v-loading="loading" class="wr">
      <template v-if="report">
        <div class="wr-range">
          <el-tag size="small" type="info">{{ report.week_start }}</el-tag>
          <span class="wr-tilde">~</span>
          <el-tag size="small" type="info">{{ report.week_end }}</el-tag>
          <el-tag v-if="report.cached" size="small" effect="plain" class="wr-cached">缓存</el-tag>
        </div>

        <div v-if="summary" class="wr-summary">{{ summary }}</div>

        <div v-if="highlights.length" class="wr-block">
          <div class="wr-block-title">本周亮点</div>
          <div class="wr-chips">
            <span v-for="h in highlights" :key="h.topic" class="wr-chip">
              {{ h.topic }}
              <em>{{ h.papers }} 篇</em>
              <i class="wr-trend" :class="'t-' + h.trend">
                {{ h.trend === 'up' ? '↑' : h.trend === 'down' ? '↓' : '→' }}
              </i>
            </span>
          </div>
        </div>

        <div class="wr-block">
          <div class="wr-block-title">活跃度</div>
          <div class="wr-stats">
            <div class="wr-stat"><b>{{ metric('total_searches') }}</b><span>检索</span></div>
            <div class="wr-stat"><b>{{ metric('total_messages') }}</b><span>提问</span></div>
            <div class="wr-stat"><b>{{ metric('active_days') }}</b><span>活跃天</span></div>
          </div>
        </div>

        <div v-if="topKeywords.length" class="wr-block">
          <div class="wr-block-title">高频关键词</div>
          <div class="wr-chips">
            <span v-for="k in topKeywords" :key="k" class="wr-chip plain">{{ k }}</span>
          </div>
        </div>

        <el-collapse class="wr-raw">
          <el-collapse-item title="查看原始 JSON" name="json">
            <pre class="wr-json">{{ JSON.stringify(report, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </template>

      <el-empty v-else-if="!loading" description="暂无周报数据" />
    </div>

    <template #footer>
      <div class="wr-footer">
        <el-button :disabled="!report" @click="downloadJson">
          <el-icon style="margin-right: 4px"><Document /></el-icon>下载 JSON
        </el-button>
        <el-button type="primary" :loading="downloading" :disabled="!report" @click="downloadPdf">
          <el-icon style="margin-right: 4px"><Printer /></el-icon>下载 PDF
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.wr {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.wr-range {
  display: flex;
  align-items: center;
  gap: 8px;
}
.wr-tilde {
  color: #9aa0a6;
}
.wr-cached {
  margin-left: 4px;
}
.wr-summary {
  font-size: 13px;
  line-height: 1.7;
  color: #5a6b8c;
  background: #f5f8ff;
  border: 1px solid #e6eeff;
  border-radius: 10px;
  padding: 10px 12px;
}
.wr-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.wr-block-title {
  font-size: 13px;
  color: #6b7280;
  font-weight: 600;
}
.wr-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.wr-chip {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 999px;
  background: #eef2f7;
  color: #1f2329;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.wr-chip.plain {
  background: #eef2f7;
  color: #5a6b8c;
}
.wr-chip em {
  font-style: normal;
  color: #9aa0a6;
  font-size: 11px;
}
.wr-trend {
  font-style: normal;
  font-weight: 700;
}
.wr-trend.t-up {
  color: #1a7f47;
}
.wr-trend.t-down {
  color: #c0392b;
}
.wr-trend.t-flat {
  color: #5a6b8c;
}
.wr-stats {
  display: flex;
  gap: 10px;
}
.wr-stat {
  flex: 1;
  background: #f7f9fc;
  border-radius: 10px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.wr-stat b {
  font-size: 18px;
  color: #2b6cff;
}
.wr-stat span {
  font-size: 12px;
  color: #9aa0a6;
}
.wr-raw {
  margin-top: 4px;
}
.wr-json {
  font-size: 11px;
  line-height: 1.5;
  color: #4b5563;
  background: #f7f9fc;
  border-radius: 8px;
  padding: 10px;
  max-height: 240px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
.wr-footer {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}
</style>
