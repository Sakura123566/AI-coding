import type { GraphData, GraphNode, GraphEdge, MemoryNode } from '../services/knowledgeGraph'

// 示例数据（前端演示用，非真实后端返回）。
// 围绕「知识图谱」领域拼一张带层级的图：中心概念 → 子方向 / 数据集 / 应用 → 方法 → 论文。
// 真实图谱应由后端经模型 / embedding 生成；这里仅用于先把 UI 骨架跑通。

const NODES: GraphNode[] = [
  // 中心概念
  {
    id: 'g-kg',
    label: '知识图谱',
    type: 'concept',
    importance: 3,
    isCenter: true,
    desc: '以「实体—关系—实体」三元组描述世界知识的结构化知识库，支撑问答、推荐、检索等下游任务。'
  },
  // 子方向（第一层）
  {
    id: 'g-rep',
    label: '知识表示学习',
    type: 'concept',
    importance: 2,
    desc: '把实体与关系映射到低维向量空间，使符号知识可被神经网络处理。'
  },
  {
    id: 'g-gnn',
    label: '图神经网络',
    type: 'concept',
    importance: 2,
    desc: '在图结构上做消息传递的神经网络，可用于节点分类、链接预测等。'
  },
  {
    id: 'g-re',
    label: '关系抽取',
    type: 'concept',
    importance: 2,
    desc: '从非结构化文本中抽取实体之间的语义关系，是构建图谱的关键环节。'
  },
  {
    id: 'g-fusion',
    label: '知识融合',
    type: 'concept',
    importance: 1,
    desc: '对齐并合并多源知识，消歧实体、统一指代。'
  },
  // 数据集（第一层）
  {
    id: 'd-freebase',
    label: 'Freebase',
    type: 'dataset',
    importance: 1,
    desc: '大型协作式结构化知识库，后被 Wikidata 吸收。'
  },
  {
    id: 'd-dbpedia',
    label: 'DBpedia',
    type: 'dataset',
    importance: 1,
    desc: '从 Wikipedia 中抽取的结构化知识库。'
  },
  {
    id: 'd-wikidata',
    label: 'Wikidata',
    type: 'dataset',
    importance: 1,
    desc: '维基媒体旗下的协作式多语言知识库，强调可追溯与可编辑。'
  },
  {
    id: 'd-yago',
    label: 'YAGO',
    type: 'dataset',
    importance: 1,
    desc: '融合 Wikipedia 与 WordNet 的大规模本体知识库。'
  },
  // 应用（第一层）
  {
    id: 'a-qa',
    label: '问答系统',
    type: 'application',
    importance: 2,
    desc: '基于图谱做可溯源的事实问答（KBQA）。'
  },
  {
    id: 'a-rec',
    label: '推荐系统',
    type: 'application',
    importance: 1,
    desc: '用图谱刻画物品与用户兴趣，提升召回与可解释性。'
  },
  {
    id: 'a-ir',
    label: '信息检索',
    type: 'application',
    importance: 1,
    desc: '将查询与文档映射到图谱做语义检索与聚合。'
  },
  {
    id: 'a-drug',
    label: '药物发现',
    type: 'application',
    importance: 1,
    desc: '用生物医学知识图谱做靶点发现与老药新用。'
  },
  // 方法（第二层）
  {
    id: 'm-transe',
    label: 'TransE',
    type: 'method',
    importance: 2,
    year: 2013,
    desc: '用「头+关系≈尾」的平移假设建模三元组，开创图谱嵌入路线。'
  },
  {
    id: 'm-transh',
    label: 'TransH',
    type: 'method',
    importance: 1,
    year: 2014,
    desc: '为不同关系映射不同超平面，缓解 TransE 在自反 / 一对多关系上的不足。'
  },
  {
    id: 'm-rotate',
    label: 'RotatE',
    type: 'method',
    importance: 2,
    year: 2019,
    desc: '用复数空间旋转建模关系，可刻画对称、反对称、逆与组合等模式。'
  },
  {
    id: 'm-rgcn',
    label: 'R-GCN',
    type: 'method',
    importance: 2,
    year: 2018,
    desc: '把图卷积推广到带关系类型的图谱，用于实体分类与链接预测。'
  },
  {
    id: 'm-distmult',
    label: 'DistMult',
    type: 'method',
    importance: 1,
    year: 2015,
    desc: '双线性打分建模三元组，简洁高效，是表示学习的重要基线。'
  },
  {
    id: 'm-node2vec',
    label: 'node2vec',
    type: 'method',
    importance: 1,
    year: 2016,
    desc: '有偏随机游走兼顾同质与结构等价性，学习网络节点表示。'
  },
  {
    id: 'm-kgbert',
    label: 'KG-BERT',
    type: 'method',
    importance: 1,
    year: 2019,
    desc: '把三元组拼成句子送入 BERT 做链接预测，引入预训练语言模型。'
  },
  // 论文（第三层）
  {
    id: 'p-1',
    label: 'TransE (NeurIPS\'13)',
    type: 'paper',
    importance: 1,
    year: 2013,
    desc: 'Translating Embeddings for Modeling Multi-relational Data。'
  },
  {
    id: 'p-2',
    label: 'TransH (AAAI\'14)',
    type: 'paper',
    importance: 1,
    year: 2014,
    desc: 'Knowledge Graph Embedding by Translating on Hyperplanes。'
  },
  {
    id: 'p-3',
    label: 'RotatE (ICLR\'19)',
    type: 'paper',
    importance: 1,
    year: 2019,
    desc: 'Knowledge Graph Embedding by Relational Rotation。'
  },
  {
    id: 'p-4',
    label: 'R-GCN (ESWC\'18)',
    type: 'paper',
    importance: 1,
    year: 2018,
    desc: 'Modeling Relational Data with Graph Convolutional Networks。'
  },
  {
    id: 'p-5',
    label: 'GNN Review (TNNLS\'20)',
    type: 'paper',
    importance: 1,
    year: 2020,
    desc: 'Graph Neural Networks: A Review of Methods and Applications。'
  },
  {
    id: 'p-6',
    label: 'node2vec (KDD\'16)',
    type: 'paper',
    importance: 1,
    year: 2016,
    desc: 'Scalable Feature Learning for Networks。'
  },
  {
    id: 'p-7',
    label: 'DistMult (ICLR\'15)',
    type: 'paper',
    importance: 1,
    year: 2015,
    desc: 'Embedding Entities and Relations for Learning and Inference。'
  },
  {
    id: 'p-8',
    label: 'KG-BERT (ACL-W\'19)',
    type: 'paper',
    importance: 1,
    year: 2019,
    desc: 'BERT for Knowledge Graph Completion。'
  }
]

const EDGES: GraphEdge[] = [
  // 中心 → 子方向 / 数据集 / 应用
  { from: 'g-kg', to: 'g-rep', relation: '包含' },
  { from: 'g-kg', to: 'g-gnn', relation: '包含' },
  { from: 'g-kg', to: 'g-re', relation: '包含' },
  { from: 'g-kg', to: 'g-fusion', relation: '包含' },
  { from: 'g-kg', to: 'd-freebase', relation: '数据源' },
  { from: 'g-kg', to: 'd-dbpedia', relation: '数据源' },
  { from: 'g-kg', to: 'd-wikidata', relation: '数据源' },
  { from: 'g-kg', to: 'd-yago', relation: '数据源' },
  { from: 'g-kg', to: 'a-qa', relation: '应用于' },
  { from: 'g-kg', to: 'a-rec', relation: '应用于' },
  { from: 'g-kg', to: 'a-ir', relation: '应用于' },
  { from: 'g-kg', to: 'a-drug', relation: '应用于' },
  // 表示学习 → 方法
  { from: 'g-rep', to: 'm-transe', relation: '方法' },
  { from: 'g-rep', to: 'm-transh', relation: '方法' },
  { from: 'g-rep', to: 'm-rotate', relation: '方法' },
  { from: 'g-rep', to: 'm-distmult', relation: '方法' },
  { from: 'g-rep', to: 'm-kgbert', relation: '方法' },
  // 图神经网络 → 方法
  { from: 'g-gnn', to: 'm-rgcn', relation: '方法' },
  { from: 'g-gnn', to: 'm-node2vec', relation: '方法' },
  { from: 'g-gnn', to: 'm-kgbert', relation: '方法' },
  // 关系抽取 → 知识融合
  { from: 'g-re', to: 'g-fusion', relation: '支撑' },
  // 方法 → 论文
  { from: 'm-transe', to: 'p-1', relation: '论文' },
  { from: 'm-transh', to: 'p-2', relation: '论文' },
  { from: 'm-rotate', to: 'p-3', relation: '论文' },
  { from: 'm-rgcn', to: 'p-4', relation: '论文' },
  { from: 'm-rgcn', to: 'p-5', relation: '论文' },
  { from: 'm-node2vec', to: 'p-6', relation: '论文' },
  { from: 'm-distmult', to: 'p-7', relation: '论文' },
  { from: 'm-kgbert', to: 'p-8', relation: '论文' }
]

export function mockGraphForKeyword(_keyword: string): GraphData {
  // 骨架阶段：无论关键词返回同一张领域图（后续由后端按关键词生成）。
  return { nodes: NODES, edges: EDGES }
}

export function mockMemories(): MemoryNode[] {
  const now = Date.now()
  return [
    {
      id: 'mem-1',
      kind: 'inspiration',
      title: '用大模型做图谱补全',
      detail: 'KG-BERT 思路再往前走一步：用 LLM 生成候选三元组，再用图谱做一致性过滤与溯原。',
      locked: true,
      createdAt: now - 1000 * 60 * 60 * 26
    },
    {
      id: 'mem-2',
      kind: 'inspiration',
      title: 'RAG + 知识图谱结合',
      detail: '把图谱当成可检索的结构化记忆，给检索增强生成提供可溯源的支撑，减少幻觉。',
      locked: false,
      createdAt: now - 1000 * 60 * 60 * 20
    },
    {
      id: 'mem-3',
      kind: 'question',
      title: 'TransE 和 RotatE 的核心区别？',
      detail: '一个用平移、一个用旋转；旋转能表达更多关系模式（对称 / 逆 / 组合）。需要更具体的对比例子。',
      locked: false,
      createdAt: now - 1000 * 60 * 60 * 12
    },
    {
      id: 'mem-4',
      kind: 'question',
      title: '图谱怎么落地到推荐？',
      detail: '用图谱刻画「用户—物品—属性」路径，做路径感知的召回与解释，但开销怎么控？',
      locked: false,
      createdAt: now - 1000 * 60 * 60 * 5
    },
    {
      id: 'mem-5',
      kind: 'inspiration',
      title: '小规模数据下用 DistMult',
      detail: '参数少、训练稳，数据不够时比复杂模型更不容易过拟合。',
      locked: false,
      createdAt: now - 1000 * 60 * 30
    }
  ]
}

// 模拟一轮对话：后端返回的新记忆节点（骨架阶段返回示例）。
export function mockSimulateRound(): MemoryNode[] {
  const now = Date.now()
  return [
    {
      id: 'mem-sim-' + now,
      kind: 'inspiration',
      title: '模拟灵感：把图谱结构当作注意力偏置',
      detail: '让模型在生成时参考图谱里实体的邻居结构，相当于给注意力加了一层结构化先验。',
      locked: false,
      createdAt: now
    },
    {
      id: 'mem-sim-q-' + now,
      kind: 'question',
      title: '这种偏置会不会放大图谱里的噪声？',
      detail: '如果图谱本身有错边，结构化先验可能反而把模型带偏，需要可关闭的开关。',
      locked: false,
      createdAt: now
    }
  ]
}
