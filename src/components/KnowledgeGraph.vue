<script setup lang="ts">
import { computed } from 'vue'
import type { Paper, ResearchReport } from '../services/research'

// 知识图谱（前端派生可视化）：后端不返回图结构，这里基于 report 的主题簇 + 论文
// 拼一张轻量 SVG 图——中心「主题」节点连各「主题簇」节点，主题簇再连其「论文」节点。
// 真正的语义图谱/embedding 属后端职责，前端只做呈现。
const props = defineProps<{
  topic?: string
  report: ResearchReport | null
  papers?: Paper[]
}>()

interface GNode {
  id: string
  label: string
  type: 'topic' | 'theme' | 'paper'
  x: number
  y: number
}
interface GEdge {
  from: string
  to: string
}

const PAPER_CAP = 6
const WIDTH = 760

const graph = computed<{ nodes: GNode[]; edges: GEdge[]; width: number; height: number }>(() => {
  const papers = props.papers ?? []
  const byId = new Map(papers.map((p) => [p.id, p]))
  const nodes: GNode[] = []
  const edges: GEdge[] = []

  const topicId = 'topic'
  nodes.push({ id: topicId, label: props.topic || '主题', type: 'topic', x: WIDTH / 2, y: 46 })

  const themes = props.report?.themes ?? []
  const themeY = 140

  if (!themes.length) {
    // 没有主题簇：把论文直接挂在主题节点下
    const shown = papers.slice(0, PAPER_CAP)
    const step = Math.min(96, (WIDTH - 80) / Math.max(1, shown.length))
    shown.forEach((p, i) => {
      const id = 'p-' + p.id
      nodes.push({
        id,
        label: p.title,
        type: 'paper',
        x: WIDTH / 2 + (i - (shown.length - 1) / 2) * step,
        y: 200
      })
      edges.push({ from: topicId, to: id })
    })
    return { nodes, edges, width: WIDTH, height: 260 }
  }

  const colW = WIDTH / themes.length
  const paperStep = Math.min(88, (colW - 48) / PAPER_CAP)
  themes.forEach((t, i) => {
    const tx = colW * (i + 0.5)
    const tid = 't-' + i
    nodes.push({ id: tid, label: t.name, type: 'theme', x: tx, y: themeY })
    edges.push({ from: topicId, to: tid })

    const linked = (t.paper_ids ?? [])
      .map((id) => byId.get(id))
      .filter((p): p is Paper => !!p)
      .slice(0, PAPER_CAP)
    const n = linked.length
    linked.forEach((p, j) => {
      const id = 'p-' + p.id + '-' + i
      nodes.push({
        id,
        label: p.title,
        type: 'paper',
        x: tx + (j - (n - 1) / 2) * paperStep,
        y: themeY + 96
      })
      edges.push({ from: tid, to: id })
    })
  })

  return { nodes, edges, width: WIDTH, height: themeY + 150 }
})

function truncate(s: string, n = 12): string {
  return s.length > n ? s.slice(0, n) + '…' : s
}
</script>

<template>
  <div class="kg">
    <div v-if="!graph.nodes.length" class="kg-empty">检索后这里会生成知识图谱</div>
    <svg
      v-else
      class="kg-svg"
      :viewBox="`0 0 ${graph.width} ${graph.height}`"
      preserveAspectRatio="xMidYMin meet"
    >
      <line
        v-for="(e, i) in graph.edges"
        :key="'e' + i"
        :x1="graph.nodes.find((n) => n.id === e.from)!.x"
        :y1="graph.nodes.find((n) => n.id === e.from)!.y"
        :x2="graph.nodes.find((n) => n.id === e.to)!.x"
        :y2="graph.nodes.find((n) => n.id === e.to)!.y"
        class="kg-edge"
      />
      <g v-for="n in graph.nodes" :key="n.id">
        <circle
          :cx="n.x"
          :cy="n.y"
          :r="n.type === 'topic' ? 26 : n.type === 'theme' ? 18 : 6"
          :class="['kg-node', 'kg-' + n.type]"
        />
        <text
          :x="n.x"
          :y="n.y + (n.type === 'paper' ? 20 : 5)"
          :class="['kg-label', 'kg-label-' + n.type]"
          text-anchor="middle"
        >{{ truncate(n.label, n.type === 'paper' ? 10 : 14) }}</text>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.kg {
  width: 100%;
}
.kg-empty {
  color: #9aa0a6;
  font-size: 13px;
  text-align: center;
  padding: 40px 0;
}
.kg-svg {
  width: 100%;
  height: auto;
  display: block;
}
.kg-edge {
  stroke: #c7d2e8;
  stroke-width: 1.5;
}
.kg-node {
  fill: #6a5cff;
}
.kg-topic {
  fill: #2b6cff;
}
.kg-theme {
  fill: #7c6bff;
}
.kg-paper {
  fill: #b9c2d6;
}
.kg-label {
  fill: #444;
  font-size: 11px;
}
.kg-label-topic {
  fill: #fff;
  font-size: 12px;
  font-weight: 600;
}
.kg-label-theme {
  fill: #3a2f8f;
  font-size: 12px;
  font-weight: 600;
}
.kg-label-paper {
  fill: #8a93a6;
  font-size: 10px;
}
</style>
