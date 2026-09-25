export interface TopicCatalogItem {
  keywords: string[]
}

export interface TopicMatch<T extends TopicCatalogItem> {
  item: T
  keyword: string
  score: number
}

export function normalizeTopicQuery(value: string): string {
  return String(value || '')
    .toLocaleLowerCase()
    .replace(/[‐‑–—]/g, '-')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function scoreKeyword(query: string, rawKeyword: string): number {
  const keyword = normalizeTopicQuery(rawKeyword)
  if (!keyword || !query.includes(keyword)) return 0

  if (query === keyword) return 1000 + keyword.length

  const isAsciiPhrase = /^[a-z0-9 .+#-]+$/.test(keyword)
  if (isAsciiPhrase) {
    const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const boundary = new RegExp(`(^|\\b)${escaped}(\\b|$)`, 'i')
    return boundary.test(query) ? 700 + keyword.length : 0
  }

  return 500 + keyword.length
}

export function findBestTopicMatch<T extends TopicCatalogItem>(
  rawQuery: string,
  catalog: T[]
): TopicMatch<T> | null {
  const query = normalizeTopicQuery(rawQuery)
  if (!query) return null

  let best: TopicMatch<T> | null = null
  for (const item of catalog) {
    for (const keyword of item.keywords) {
      const score = scoreKeyword(query, keyword)
      if (!score) continue
      if (
        !best ||
        score > best.score ||
        (score === best.score && normalizeTopicQuery(keyword).length > normalizeTopicQuery(best.keyword).length)
      ) {
        best = { item, keyword, score }
      }
    }
  }
  return best
}