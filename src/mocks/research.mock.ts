import type { Paper, ResearchReport, ResearchResponse } from '../services/research'

// 示例数据：用于前端先在无后端情况下跑通 UI。
// 按真实契约结构返回：papers 带 id/source/url；report 含
// overview/themes/research_trends/reading_path/exploration_questions/limitations。
// 真实论文信息与主题归纳需由后端经 MCP 生成，这里只是前端演示样本。

interface CatalogItem {
  keywords: string[]
  label: string
  papers: Paper[]
}

// 由一批论文自动拼出一份「导航报告」（演示用，结构对齐真实契约）
function buildReport(papers: Paper[], label: string): ResearchReport {
  const ids = papers.map((p) => p.id)
  return {
    overview: `围绕「${label}」主题，下面这些论文覆盖了从基础方法到前沿应用的脉络，可作为入门与深入阅读的主线。`,
    themes: [
      {
        name: '基础方法',
        description: '该方向的核心建模思路与经典算法，建议先建立整体认识。',
        paper_ids: ids.slice(0, Math.min(3, ids.length))
      },
      {
        name: '前沿进展',
        description: '近期具有代表性的改进、扩展或落地工作。',
        paper_ids: ids.slice(3, Math.min(6, ids.length))
      }
    ],
    research_trends: [
      '方法向更高效、更可扩展演进',
      '与预训练 / 大模型能力进一步融合',
      '更关注可解释性与结果可溯源'
    ],
    reading_path: ids.slice(0, 4).map((id, i) => ({
      step: i + 1,
      paper_ids: [id],
      reason: `先读第 ${i + 1} 篇，理解「${label}」的基本设定与问题定义。`
    })),
    exploration_questions: [
      '该方向当前最主要的开放问题是什么？',
      '如何把其中的方法迁移到你的具体场景？',
      '有哪些公开数据集可以用来复现实验？'
    ],
    limitations: '以上为前端演示用的示例归纳；真实论文检索与主题归纳由后端通过 MCP 完成。'
  }
}

const LLM_PAPERS: Paper[] = [
  { id: 'LLM-1', title: 'Attention Is All You Need', authors: ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar', 'et al.'], year: 2017, source: 'NeurIPS', url: 'https://arxiv.org/abs/1706.03762', abstract: '提出 Transformer 架构，完全基于注意力机制，摒弃循环与卷积，在机器翻译任务上取得 SOTA，奠定了后续大模型的基础。' },
  { id: 'LLM-2', title: 'Language Models are Few-Shot Learners (GPT-3)', authors: ['Tom B. Brown', 'Benjamin Mann', 'Nick Ryder', 'et al.'], year: 2020, source: 'NeurIPS', url: 'https://arxiv.org/abs/2005.14165', abstract: '展示大规模自回归语言模型通过少样本提示即可完成多种任务，无需梯度更新，开启「上下文学习」范式。' },
  { id: 'LLM-3', title: 'LLaMA: Open and Efficient Foundation Language Models', authors: ['Hugo Touvron', 'Thibaut Lavril', 'Gautier Izacard', 'et al.'], year: 2023, source: 'arXiv', url: 'https://arxiv.org/abs/2302.13971', abstract: '在公开数据上训练的高效基础模型，证明小模型也可具备强竞争力，推动开源大模型生态发展。' },
  { id: 'LLM-4', title: 'Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks', authors: ['Patrick Lewis', 'Ethan Perez', 'Aleksandra Piktus', 'et al.'], year: 2020, source: 'NeurIPS', url: 'https://arxiv.org/abs/2005.11401', abstract: '将参数化模型与非参数化检索器结合，提升知识密集型任务的事实性与可溯源性，是 RAG 的经典工作。' },
  { id: 'LLM-5', title: 'GPT-4 Technical Report', authors: ['OpenAI'], year: 2023, source: 'arXiv', url: 'https://arxiv.org/abs/2303.08774', abstract: '介绍 GPT-4 在多模态、推理与专业考试上的能力跃迁，并讨论对齐、评估与局限性。' },
  { id: 'LLM-6', title: 'LoRA: Low-Rank Adaptation of Large Language Models', authors: ['Edward J. Hu', 'Yelong Shen', 'Phillip Wallis', 'et al.'], year: 2021, source: 'ICLR', url: 'https://arxiv.org/abs/2106.09685', abstract: '通过低秩矩阵注入微调少量参数即可逼近全量微调效果，极大降低大模型适配成本。' },
  { id: 'LLM-7', title: 'Training Language Models to Follow Instructions (InstructGPT)', authors: ['Long Ouyang', 'Jeff Wu', 'Xu Jiang', 'et al.'], year: 2022, source: 'NeurIPS', url: 'https://arxiv.org/abs/2203.02155', abstract: '用人类反馈强化学习（RLHF）让模型更贴合用户意图，是 ChatGPT 类产品的训练范式基础。' },
  { id: 'LLM-8', title: 'FlashAttention: Fast and Memory-Efficient Exact Attention', authors: ['Tri Dao', 'Daniel Y. Fu', 'Stefano Ermon', 'et al.'], year: 2022, source: 'NeurIPS', url: 'https://arxiv.org/abs/2205.14135', abstract: '通过 IO 感知的精确注意力算法大幅提速并节省显存，成为长上下文训练的关键组件。' }
]

const KG_PAPERS: Paper[] = [
  { id: 'KG-1', title: 'Translating Embeddings for Modeling Multi-relational Data (TransE)', authors: ['Antoine Bordes', 'Nicolas Usunier', 'Alberto Garcia-Duran', 'et al.'], year: 2013, source: 'NeurIPS', url: 'https://arxiv.org/abs/1301.3485', abstract: '将实体与关系嵌入到同一向量空间，用「头+关系≈尾」的平移假设建模知识图谱，开创图谱嵌入路线。' },
  { id: 'KG-2', title: 'Knowledge Graph Embedding by Translating on Hyperplanes (TransH)', authors: ['Zhen Wang', 'Jianwen Zhang', 'Jianlin Feng', 'et al.'], year: 2014, source: 'AAAI', url: 'https://arxiv.org/abs/1407.5239', abstract: '为不同关系映射不同超平面，缓解 TransE 在自反/一对多关系上的表达力不足。' },
  { id: 'KG-3', title: 'RotatE: Knowledge Graph Embedding by Relational Rotation', authors: ['Zhiqing Sun', 'Zhi-Hong Deng', 'Jian-Yun Nie', 'et al.'], year: 2019, source: 'ICLR', url: 'https://arxiv.org/abs/1902.10197', abstract: '用复数空间中的旋转建模关系，可刻画对称、反对称、逆与组合等多种关系模式。' },
  { id: 'KG-4', title: 'Modeling Relational Data with Graph Convolutional Networks (R-GCN)', authors: ['Michael Schlichtkrull', 'Thomas N. Kipf', 'Peter Bloem', 'et al.'], year: 2018, source: 'ESWC', url: 'https://arxiv.org/abs/1703.06103', abstract: '将图卷积网络推广到带关系类型的知识图谱，用于实体分类与链接预测。' },
  { id: 'KG-5', title: 'Graph Neural Networks: A Review of Methods and Applications', authors: ['Zonghan Wu', 'Shirui Pan', 'Fengwen Chen', 'et al.'], year: 2020, source: 'IEEE TNNLS', url: 'https://arxiv.org/abs/1812.08434', abstract: '系统梳理图神经网络的设计范式、变体与在图谱、化学、推荐等领域的应用。' },
  { id: 'KG-6', title: 'node2vec: Scalable Feature Learning for Networks', authors: ['Aditya Grover', 'Jure Leskovec'], year: 2016, source: 'KDD', url: 'https://arxiv.org/abs/1607.00653', abstract: '通过有偏随机游走兼顾同质与结构等价性，学习网络节点的低维表示。' },
  { id: 'KG-7', title: 'Embedding Entities and Relations for Learning and Inference (DistMult)', authors: ['Bishan Yang', 'Wen-tau Yih', 'Xiaodong He', 'et al.'], year: 2015, source: 'ICLR', url: 'https://arxiv.org/abs/1412.6575', abstract: '用双线性打分建模三元组，简洁高效，是知识图谱表示学习的重要基线。' },
  { id: 'KG-8', title: 'KG-BERT: BERT for Knowledge Graph Completion', authors: ['Liang Yao', 'Chengsheng Mao', 'Yuan Luo'], year: 2019, source: 'ACL Workshop', url: 'https://arxiv.org/abs/1909.03193', abstract: '将三元组拼成句子送入 BERT 做链接预测，把预训练语言模型引入图谱补全。' }
]

const REC_PAPERS: Paper[] = [
  { id: 'REC-1', title: 'Wide & Deep Learning for Recommender Systems', authors: ['Heng-Tze Cheng', 'Levent Koc', 'Jeremiah Harmsen', 'et al.'], year: 2016, source: 'DLRS', url: 'https://arxiv.org/abs/1606.02380', abstract: '记忆与泛化兼顾：宽层记历史，深层做泛化，是工业推荐系统的经典结构。' },
  { id: 'REC-2', title: 'DeepFM: A Factorization-Machine based Neural Network', authors: ['Huifeng Guo', 'Ruiming Tang', 'Yunming Ye', 'et al.'], year: 2017, source: 'IJCAI', url: 'https://arxiv.org/abs/1703.05170', abstract: '用 FM 与 DNN 共享特征嵌入，端到端建模低阶与高阶特征交叉。' },
  { id: 'REC-3', title: 'Deep Interest Network (DIN) for CTR Prediction', authors: ['Guorui Zhou', 'Xiaoqiang Zhu', 'Chenru Song', 'et al.'], year: 2018, source: 'KDD', url: 'https://arxiv.org/abs/1706.06978', abstract: '以用户历史行为注意力刻画兴趣多样性，显著提升点击率预估效果。' },
  { id: 'REC-4', title: 'Neural Collaborative Filtering', authors: ['Xiangnan He', 'Lizi Liao', 'Hanwang Zhang', 'et al.'], year: 2017, source: 'WWW', url: 'https://arxiv.org/abs/1708.05031', abstract: '用神经网络替代内积建模用户-物品交互，提升协同过滤表达能力。' },
  { id: 'REC-5', title: 'Item2Vec: Neural Item Embedding for Recommendation', authors: ['Oren Barkan', 'Noam Koenigstein'], year: 2016, source: 'ICDM', url: 'https://arxiv.org/abs/1603.04259', abstract: '将 Word2Vec 思想迁移到物品序列，学习物品相似度用于召回。' },
  { id: 'REC-6', title: 'Sampling-Bias-Corrected Neural Modeling (Two-Tower)', authors: ['Xinyang Yi', 'Ji Yang', 'Lichan Hong', 'et al.'], year: 2019, source: 'RecSys', url: 'https://arxiv.org/abs/1904.08575', abstract: '双塔召回模型并校正采样偏差，是大规模召回服务的常用方案。' },
  { id: 'REC-7', title: 'Deep & Cross Network (DCN) for Ad Click Prediction', authors: ['Ruoxi Wang', 'Bin Fu', 'Gang Fu', 'et al.'], year: 2017, source: 'ADKDD', url: 'https://arxiv.org/abs/1708.05123', abstract: '显式构造特征交叉层，自动学习有界阶数的特征组合。' }
]

const RL_PAPERS: Paper[] = [
  { id: 'RL-1', title: 'Human-level Control through Deep Reinforcement Learning (DQN)', authors: ['Volodymyr Mnih', 'Koray Kavukcuoglu', 'David Silver', 'et al.'], year: 2015, source: 'Nature', url: 'https://arxiv.org/abs/1312.5602', abstract: '用深度网络 + 经验回放逼近 Q 值，在 Atari 上达到人类水平，标志深度强化学习突破。' },
  { id: 'RL-2', title: 'Proximal Policy Optimization (PPO) Algorithms', authors: ['John Schulman', 'Filip Wolski', 'Prafulla Dhariwal', 'et al.'], year: 2017, source: 'arXiv', url: 'https://arxiv.org/abs/1707.06347', abstract: '以裁剪的目标函数稳定策略更新，简单高效，成为 RLHF 与 Agent 训练的主流算法。' },
  { id: 'RL-3', title: 'Asynchronous Methods for Deep RL (A3C)', authors: ['Volodymyr Mnih', 'Adrià Puigdomènech Badia', 'Mehdi Mirza', 'et al.'], year: 2016, source: 'ICML', url: 'https://arxiv.org/abs/1602.01783', abstract: '多 Actor 异步并行收集经验，加速训练且无需大回放池。' },
  { id: 'RL-4', title: 'Mastering the Game of Go with AlphaGo', authors: ['David Silver', 'Aja Huang', 'Chris J. Maddison', 'et al.'], year: 2016, source: 'Nature', url: 'https://arxiv.org/abs/1712.01815', abstract: '结合策略网络、价值网络与蒙特卡洛树搜索，首次战胜职业棋手。' },
  { id: 'RL-5', title: 'Continuous Control with Deep Reinforcement Learning (DDPG)', authors: ['Timothy P. Lillicrap', 'Jonathan J. Hunt', 'Alexander Pritzel', 'et al.'], year: 2015, source: 'ICLR', url: 'https://arxiv.org/abs/1509.02971', abstract: '将 DQN 思路扩展到连续动作空间，基于 Actor-Critic 的离线策略算法。' },
  { id: 'RL-6', title: 'Trust Region Policy Optimization (TRPO)', authors: ['John Schulman', 'Sergey Levine', 'Philipp Moritz', 'et al.'], year: 2015, source: 'ICML', url: 'https://arxiv.org/abs/1502.05477', abstract: '以信赖域约束保证策略更新的单调性，训练更稳定。' },
  { id: 'RL-7', title: 'Soft Actor-Critic (SAC): Off-Policy Maximum Entropy RL', authors: ['Tuomas Haarnoja', 'Aurick Zhou', 'Pieter Abbeel', 'et al.'], year: 2018, source: 'ICML', url: 'https://arxiv.org/abs/1801.01290', abstract: '最大熵框架下的离线策略 Actor-Critic，兼顾样本效率与探索，适合连续控制。' }
]

const CATALOG: CatalogItem[] = [
  {
    keywords: ['大语言模型', 'llm', '大模型', 'language model', 'gpt', 'transformer', '预训练', 'pretrain', 'chatgpt', '注意力', 'attention', 'rag', '检索增强', 'agent', '指令微调', 'rlhf', 'lora'],
    label: '大语言模型',
    papers: LLM_PAPERS
  },
  {
    keywords: ['知识图谱', 'knowledge graph', '图谱', '知识表示', 'knowledge', '实体', '关系抽取', '知识融合', 'embedding', '表示学习', 'graph neural'],
    label: '知识图谱',
    papers: KG_PAPERS
  },
  {
    keywords: ['推荐', 'recommend', 'recsys', '协同过滤', '排序', 'ranking', '点击率', 'ctr', '召回'],
    label: '推荐系统',
    papers: REC_PAPERS
  },
  {
    keywords: ['强化学习', 'reinforcement', 'reinforcement learning', 'rl', '奖励', 'reward', '策略梯度', 'policy gradient', 'ppo'],
    label: '强化学习',
    papers: RL_PAPERS
  }
]

// 命中任一关键词即返回该主题的论文(按 limit 截断)与报告；都没有命中 → 返回空（触发「没找到」趣味空态）。
export function mockResearchForTopic(keyword: string, limit = 10): ResearchResponse {
  const t = (keyword ?? '').toLowerCase()
  for (const cat of CATALOG) {
    if (cat.keywords.some((k) => t.includes(k.toLowerCase()))) {
      const papers = cat.papers.slice(0, limit)
      return {
        status: 'success',
        keyword,
        resolvedKeyword: null,
        count: papers.length,
        papers,
        report: buildReport(papers, cat.label),
        reportError: null,
        warnings: [],
        message: null
      }
    }
  }
  return {
    status: 'success',
    keyword,
    resolvedKeyword: null,
    count: 0,
    papers: [],
    report: null,
    reportError: null,
    warnings: [],
    message: null
  }
}
