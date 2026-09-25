<script setup lang="ts">
import { computed } from 'vue'
import type { Paper, ResearchReport } from '../services/research'

const props = defineProps<{
  report: ResearchReport | null
  papers?: Paper[]
  // 报告降级：论文有、但报告没生成（report 为 null 且 report_error 有值）时的原因
  reportError?: string | null
}>()

// paper_ids -> 标题，便于在主题/阅读路线里展示可读的论文名
const titleById = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const p of props.papers ?? []) map[p.id] = p.titleZh || p.title
  return map
})
function titleOf(id: string): string {
  return titleById.value[id] ?? id
}
</script>

<template>
  <div class="research-report">
    <!-- 报告降级：论文有、但报告未生成，展示错误原因而非假装成功 -->
    <el-alert
      v-if="!report && reportError"
      type="warning"
      title="研究导航报告生成失败"
      :description="reportError"
      show-icon
    />
    <template v-if="report">
      <el-card shadow="never">
        <template #header>方向概览</template>
        <p class="summary">{{ report.overview }}</p>
    </el-card>

    <el-card v-if="report.themes.length" shadow="never" class="block">
      <template #header>核心主题</template>
      <div v-for="(t, i) in report.themes" :key="i" class="theme">
        <div class="theme-name">{{ t.name }}</div>
        <div class="theme-desc">{{ t.description }}</div>
        <div class="theme-papers">
          <el-tag
            v-for="pid in t.paper_ids"
            :key="pid"
            class="tag"
            type="info"
            size="small"
          >{{ titleOf(pid) }}</el-tag>
        </div>
      </div>
    </el-card>

    <el-card v-if="report.research_trends.length" shadow="never" class="block">
      <template #header>研究趋势</template>
      <div class="tags">
        <el-tag v-for="(d, i) in report.research_trends" :key="i" class="tag" type="info">
          {{ d }}
        </el-tag>
      </div>
    </el-card>

    <el-card v-if="report.reading_path.length" shadow="never" class="block">
      <template #header>推荐阅读路线</template>
      <ol class="roadmap">
        <li v-for="(s, i) in report.reading_path" :key="i">
          <span class="step-reason">{{ s.reason }}</span>
          <div class="theme-papers">
            <el-tag
              v-for="pid in s.paper_ids"
              :key="pid"
              class="tag"
              type="success"
              size="small"
            >{{ titleOf(pid) }}</el-tag>
          </div>
        </li>
      </ol>
    </el-card>

    <el-card v-if="report.exploration_questions.length" shadow="never" class="block">
      <template #header>值得追问</template>
      <ul class="questions">
        <li v-for="(q, i) in report.exploration_questions" :key="i">{{ q }}</li>
      </ul>
    </el-card>

    <el-card v-if="report.limitations" shadow="never" class="block">
      <template #header>检索与归纳局限</template>
      <p class="limitations">{{ report.limitations }}</p>
    </el-card>
    </template>
  </div>
</template>

<style scoped>
.research-report {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.summary {
  margin: 0;
  line-height: 1.7;
  color: #333;
}
.theme {
  padding: 10px 0;
  border-bottom: 1px dashed #eef0f2;
}
.theme:last-child {
  border-bottom: none;
}
.theme-name {
  font-weight: 600;
  color: #1f2329;
}
.theme-desc {
  margin-top: 4px;
  font-size: 13px;
  color: #666;
  line-height: 1.6;
}
.theme-papers {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.roadmap {
  margin: 0;
  padding-left: 20px;
  line-height: 1.9;
  color: #333;
}
.roadmap li {
  margin-bottom: 6px;
}
.step-reason {
  color: #333;
}
.questions {
  margin: 0;
  padding-left: 20px;
  line-height: 1.9;
  color: #333;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.limitations {
  margin: 0;
  line-height: 1.7;
  color: #888;
  font-size: 13px;
}
</style>
