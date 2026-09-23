<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  generateGraph,
  parseArticle,
  type GraphData,
  type GraphNode,
  type GraphNodeType
} from '../services/knowledgeGraph'

const props = withDefaults(defineProps<{ keyword?: string }>(), { keyword: '知识图谱' })

const keyword = ref(props.keyword || '知识图谱')
const loading = ref(false)
const graphData = ref<GraphData | null>(null)
const searchText = ref('')
const locked = ref(false)

const hoverId = ref<string | null>(null)
const selectedId = ref<string | null>(null)
const dialogVisible = ref(false)

const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

// —— 径向/同心环布局（对齐 29f5 的 radialTree 观感）——
function computeLayout(data: GraphData, W: number, H: number): Map<string, { x: number; y: number }> {
  const { nodes, edges } = data
  const adj = new Map<string, Set<string>>()
  nodes.forEach((n) => adj.set(n.id, new Set()))
  edges.forEach((e) => {
    if (adj.has(e.from) && adj.has(e.to)) {
      adj.get(e.from)!.add(e.to)
      adj.get(e.to)!.add(e.from)
    }
  })
  const center = nodes.find((n) => n.isCenter) ?? nodes[0]
  const layer = new Map<string, number>()
  const queue: string[] = []
  if (center) {
    layer.set(center.id, 0)
    queue.push(center.id)
  }
  while (queue.length) {
    const id = queue.shift() as string
    const l = layer.get(id) as number
    for (const nb of adj.get(id) as Set<string>) {
      if (!layer.has(nb)) {
        layer.set(nb, l + 1)
        queue.push(nb)
      }
    }
  }
  const maxLayer = Math.max(0, ...Array.from(layer.values()))
  nodes.forEach((n) => {
    if (!layer.has(n.id)) layer.set(n.id, maxLayer + 1)
  })

  const pos = new Map<string, { x: number; y: number }>()
  const cx = W / 2
  const cy = H / 2
  const byLayer = new Map<number, string[]>()
  layer.forEach((l, id) => {
    if (!byLayer.has(l)) byLayer.set(l, [])
    byLayer.get(l)!.push(id)
  })
  const ringGap = Math.min(W, H) * 0.15
  byLayer.forEach((ids, l) => {
    const r = l * ringGap
    ids.forEach((id, i) => {
      const a = -Math.PI / 2 + (i / ids.length) * 2 * Math.PI
      pos.set(id, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) })
    })
  })
  return pos
}

const TYPE_COLORS: Record<GraphNodeType, string> = {
  concept: '#2b6cff',
  paper: '#7c6bff',
  method: '#19b37d',
  dataset: '#f59e0b',
  application: '#ef5da8'
}
const TYPE_LABELS: Record<GraphNodeType, string> = {
  concept: '概念',
  paper: '论文',
  method: '方法',
  dataset: '数据集',
  application: '应用'
}
const legendItems = computed(() =>
  (Object.keys(TYPE_COLORS) as GraphNodeType[]).map((t) => ({
    type: t,
    color: TYPE_COLORS[t],
    label: TYPE_LABELS[t]
  }))
)
const categories = computed(() =>
  (Object.keys(TYPE_COLORS) as GraphNodeType[]).map((t) => ({
    name: TYPE_LABELS[t],
    itemStyle: { color: TYPE_COLORS[t] }
  }))
)

function radiusOf(n: GraphNode): number {
  return n.importance === 3 ? 44 : n.importance === 2 ? 30 : 20
}

function buildOption(): echarts.EChartsOption {
  const data = graphData.value
  if (!data || !chart) return {}
  const W = chart.getWidth() || 960
  const H = chart.getHeight() || 620
  const pos = computeLayout(data, W, H)
  const typeKeys = Object.keys(TYPE_COLORS) as GraphNodeType[]
  const nodeList = data.nodes.map((n) => {
    const match = !!searchText.value && locked.value && n.label.includes(searchText.value)
    const dim = !!searchText.value && locked.value && !match
    return {
      id: n.id,
      name: n.id,
      category: typeKeys.indexOf(n.type),
      symbolSize: radiusOf(n),
      x: pos.get(n.id)!.x,
      y: pos.get(n.id)!.y,
      itemStyle: {
        opacity: dim ? 0.18 : 1,
        borderColor: '#fff',
        borderWidth: 2,
        shadowBlur: 9,
        shadowColor: 'rgba(40,70,150,.18)'
      },
      label: {
        show: n.importance >= 2,
        formatter: () => n.label,
        color: '#414c60',
        fontSize: n.importance >= 2 ? 12 : 11,
        textBorderColor: '#fff',
        textBorderWidth: 3
      },
      _node: n
    }
  })
  const linkList = data.edges.map((e) => ({
    source: e.from,
    target: e.to,
    label: { show: false },
    lineStyle: { color: '#a9bcd8', width: 1.2, opacity: 0.55, curveness: 0.05 }
  }))
  return {
    tooltip: {
      show: true,
      formatter: (p: any) =>
        p.dataType === 'node'
          ? `<b>${p.data._node.label}</b><br/>${TYPE_LABELS[p.data._node.type as GraphNodeType]} · 重要度 ${'★'.repeat(
              p.data._node.importance
            )}${p.data._node.year ? ' · ' + p.data._node.year : ''}<br/>${p.data._node.desc || ''}`
          : ''
    },
    series: [
      {
        type: 'graph',
        layout: 'none',
        roam: true,
        draggable: false,
        data: nodeList,
        links: linkList,
        categories: categories.value,
        emphasis: {
          focus: 'adjacency',
          scale: 1.08,
          label: { show: true }
        },
        left: '3%',
        right: '3%',
        top: '5%',
        bottom: '5%'
      }
    ]
  }
}

function renderChart() {
  if (!chart) return
  chart.setOption(buildOption(), true)
}

function openNode(id: string) {
  selectedId.value = id
  dialogVisible.value = true
}

const selectedNode = computed(() => {
  const data = graphData.value
  if (!data || !selectedId.value) return null
  return data.nodes.find((n) => n.id === selectedId.value) ?? null
})
const relatedNodes = computed(() => {
  const data = graphData.value
  if (!data || !selectedId.value) return []
  const out: { node: GraphNode; relation?: string; dir: 'out' | 'in' }[] = []
  data.edges.forEach((e) => {
    if (e.from === selectedId.value) {
      const n = data.nodes.find((x) => x.id === e.to)
      if (n) out.push({ node: n, relation: e.relation, dir: 'out' })
    } else if (e.to === selectedId.value) {
      const n = data.nodes.find((x) => x.id === e.from)
      if (n) out.push({ node: n, relation: e.relation, dir: 'in' })
    }
  })
  return out
})

async function generate() {
  const kw = keyword.value.trim()
  if (!kw) {
    ElMessage.warning('请输入关键词')
    return
  }
  loading.value = true
  try {
    graphData.value = await generateGraph(kw, { tone: 'professional', sentences: 2 })
    renderChart()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '生成失败')
  } finally {
    loading.value = false
  }
}

async function parseText() {
  try {
    const { value } = await ElMessageBox.prompt('粘贴一段文章，自动抽取实体关系生成知识图谱', '解析文章', {
      inputType: 'textarea',
      inputPlaceholder: '在此粘贴文本…',
      confirmButtonText: '解析',
      cancelButtonText: '取消'
    })
    if (!value) return
    loading.value = true
    graphData.value = await parseArticle(value, { tone: 'professional', sentences: 2 })
    renderChart()
  } catch {
    /* 取消 */
  } finally {
    loading.value = false
  }
}

function toggleLock() {
  locked.value = !locked.value
  if (!locked.value) searchText.value = ''
  renderChart()
}

function resetView() {
  chart?.dispatchAction({ type: 'restore' })
  renderChart()
}

function onResize() {
  chart?.resize()
}

onMounted(() => {
  if (chartEl.value) {
    chart = echarts.init(chartEl.value)
    chart.on('click', (p: any) => {
      if (p.dataType === 'node') openNode(p.name)
    })
    chart.on('mouseover', (p: any) => {
      if (p.dataType === 'node') hoverId.value = p.name
    })
    chart.on('mouseout', () => {
      hoverId.value = null
    })
    window.addEventListener('resize', onResize)
    generate()
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})

watch(
  () => props.keyword,
  (k) => {
    if (k) {
      keyword.value = k
      generate()
    }
  }
)
watch(searchText, renderChart)
</script>

<template>
  <div class="kg-wrap">
    <!-- 工具条 -->
    <div class="kg-toolbar">
      <div class="kg-search">
        <el-input
          v-model="keyword"
          placeholder="输入关键词，生成知识图谱"
          clearable
          style="width: 240px"
          @keyup.enter="generate"
        >
          <template #append>
            <el-button :loading="loading" @click="generate">生成网络</el-button>
          </template>
        </el-input>
        <el-button @click="parseText">解析文章</el-button>
      </div>

      <div class="kg-tools">
        <el-input
          v-model="searchText"
          placeholder="搜索节点"
          clearable
          size="small"
          style="width: 150px"
          :disabled="locked"
        />
        <el-button size="small" :type="locked ? 'primary' : 'default'" @click="toggleLock">
          {{ locked ? '解锁' : '锁定' }}
        </el-button>
        <el-button size="small" @click="resetView">适应</el-button>
      </div>
    </div>

    <!-- 图例 -->
    <div class="kg-legend">
      <span v-for="it in legendItems" :key="it.type" class="kg-legend-item">
        <i class="kg-legend-dot" :style="{ background: it.color }" />
        {{ it.label }}
      </span>
    </div>

    <!-- 画布 -->
    <div class="kg-canvas">
      <div ref="chartEl" class="kg-echart"></div>
      <div v-if="!graphData" class="kg-empty">输入关键词生成知识图谱，或点击「解析文章」</div>
      <div class="kg-zoomhint">滚轮缩放 · 拖拽平移 · 点击节点查看详情</div>
    </div>

    <!-- 节点详情弹窗（点击节点触发） -->
    <el-dialog
      v-model="dialogVisible"
      :title="selectedNode?.label || ''"
      width="520px"
      align-center
      @closed="selectedId = null"
    >
      <div v-if="selectedNode" class="kg-detail">
        <div class="kg-detail-tags">
          <el-tag :color="TYPE_COLORS[selectedNode.type]" effect="dark" style="color: #fff; border: none">
            {{ TYPE_LABELS[selectedNode.type] }}
          </el-tag>
          <el-tag v-if="selectedNode.importance" type="warning" effect="plain">
            重要度 {{ '★'.repeat(selectedNode.importance) }}
          </el-tag>
          <el-tag v-if="selectedNode.year" effect="plain">{{ selectedNode.year }}</el-tag>
        </div>
        <p class="kg-detail-desc">{{ selectedNode.desc || '暂无描述' }}</p>

        <div class="kg-detail-rel">
          <div class="kg-detail-rel-title">相关节点（{{ relatedNodes.length }}）</div>
          <ul v-if="relatedNodes.length" class="kg-rel-list">
            <li v-for="r in relatedNodes" :key="r.node.id" @click="openNode(r.node.id)">
              <span class="kg-rel-dir" :class="r.dir">{{ r.dir === 'out' ? '→' : '←' }}</span>
              <span class="kg-rel-rel">{{ r.relation || '关联' }}</span>
              <span class="kg-rel-name">{{ r.node.label }}</span>
            </li>
          </ul>
          <div v-else class="kg-rel-empty">该节点暂无关联</div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.kg-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.kg-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.kg-search {
  display: flex;
  gap: 8px;
  align-items: center;
}
.kg-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.kg-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 12px;
  color: #5a6b8c;
}
.kg-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.kg-legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
.kg-canvas {
  position: relative;
  width: 100%;
  height: 560px;
  background: #fff;
  border: 1px solid #eef0f2;
  border-radius: 12px;
  overflow: hidden;
}
.kg-echart {
  width: 100%;
  height: 100%;
}
.kg-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9aa0a6;
  font-size: 14px;
}
.kg-zoomhint {
  position: absolute;
  left: 12px;
  bottom: 10px;
  font-size: 11px;
  color: #9aa0a6;
  background: rgba(255, 255, 255, 0.7);
  padding: 2px 8px;
  border-radius: 6px;
  pointer-events: none;
}
.kg-detail-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.kg-detail-desc {
  font-size: 14px;
  line-height: 1.7;
  color: #2b2f36;
  margin: 0 0 16px;
}
.kg-detail-rel-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2329;
  margin-bottom: 8px;
}
.kg-rel-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 240px;
  overflow: auto;
}
.kg-rel-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.kg-rel-list li:hover {
  background: #eef3ff;
}
.kg-rel-dir {
  font-weight: 700;
  color: #2b6cff;
}
.kg-rel-dir.in {
  color: #7c6bff;
}
.kg-rel-rel {
  font-size: 12px;
  color: #8a93a6;
  min-width: 42px;
}
.kg-rel-name {
  font-size: 13px;
  color: #1f2329;
}
.kg-rel-empty {
  font-size: 13px;
  color: #9aa0a6;
}
</style>
