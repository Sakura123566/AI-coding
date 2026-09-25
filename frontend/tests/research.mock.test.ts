import assert from 'node:assert/strict'
import test from 'node:test'

import { mockResearchForTopic } from '../src/mocks/research.mock.ts'

test('GNN aliases resolve to the GNN demo catalog', () => {
  for (const query of ['GNN', 'gnn', '图神经网络', 'graph neural networks']) {
    const result = mockResearchForTopic(query, 10)
    assert.equal(result.papers[0]?.id, 'GNN-1')
    assert.match(result.report?.overview || '', /图神经网络/)
  }
})

test('knowledge graph stays separate from GNN', () => {
  const result = mockResearchForTopic('知识图谱', 10)
  assert.equal(result.papers[0]?.id, 'KG-1')
  assert.match(result.report?.overview || '', /知识图谱/)
})

test('unknown demo topic returns a demo warning and empty result', () => {
  const result = mockResearchForTopic('完全不存在的演示主题', 10)
  assert.equal(result.count, 0)
  assert.match(result.warnings.join(' '), /演示数据/)
})