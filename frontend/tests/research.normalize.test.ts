import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizePaper } from '../src/services/research.ts'

test('normalizes Chinese paper title and summary fields', () => {
  const paper = normalizePaper({
    id: 'P1',
    title: 'Graph Neural Networks',
    title_zh: '图神经网络',
    abstract: 'English abstract',
    abstract_zh: '中文摘要',
    abstract_summary_zh: '中文短摘要',
    translation_status: 'translated',
    translation_note: null,
    url: 'https://example.com/paper',
    source: 'OpenAlex'
  })

  assert.equal(paper.titleZh, '图神经网络')
  assert.equal(paper.abstractZh, '中文摘要')
  assert.equal(paper.abstractSummaryZh, '中文短摘要')
  assert.equal(paper.translationStatus, 'translated')
})