import assert from 'node:assert/strict'
import test from 'node:test'

import { findBestTopicMatch, normalizeTopicQuery } from '../src/utils/topicMatcher.ts'

const catalog = [
  { id: 'llm', keywords: ['大语言模型', 'llm', 'language model'] },
  { id: 'gnn', keywords: ['gnn', 'graph neural', 'graph neural networks', '图神经网络'] },
  { id: 'kg', keywords: ['知识图谱', 'knowledge graph'] }
]

test('normalizes whitespace and case', () => {
  assert.equal(normalizeTopicQuery('  Graph   Neural Networks  '), 'graph neural networks')
})

test('prefers the longer and more specific GNN match', () => {
  assert.equal(findBestTopicMatch('graph neural networks', catalog)?.item.id, 'gnn')
  assert.equal(findBestTopicMatch('GNN', catalog)?.item.id, 'gnn')
  assert.equal(findBestTopicMatch('图神经网络', catalog)?.item.id, 'gnn')
})

test('keeps knowledge graph separate from GNN', () => {
  assert.equal(findBestTopicMatch('knowledge graph', catalog)?.item.id, 'kg')
  assert.equal(findBestTopicMatch('知识图谱', catalog)?.item.id, 'kg')
})