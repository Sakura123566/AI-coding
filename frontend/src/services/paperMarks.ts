// 收藏 / 观看记录同步到后端。
//
// 为什么要同步：以前这两样只写在浏览器 localStorage 里，换设备或清缓存就没了；
// 而且后端算长期记忆图谱时看不到它们，图谱里就只有「搜过的主题」和「聊过的内容」。
// 同步之后，收藏和点开看过的论文也会变成图谱里的关键词节点。
//
// 未登录时不同步（后端这些接口要登录），本地照常能用，等登录后再一次性补上去。
const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export interface MarkPaper {
  id?: string
  title?: string
  title_original?: string
  year?: number | null
  source?: string | null
  url?: string | null
  authors?: string[]
  abstract?: string | null
  topic?: string | null
}

function authHeaders(token: string): Record<string, string> {
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
}

async function post(path: string, token: string, body: unknown): Promise<any> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(body)
  })
  if (!res.ok) throw new Error('HTTP ' + res.status)
  return res.json()
}

/** 收藏一篇 */
export function favoritePaper(token: string, paper: MarkPaper, topic?: string) {
  return post('/api/kg/papers/favorite', token, { paper, topic: topic ?? null })
}

/** 取消收藏 */
export function unfavoritePaper(token: string, paper: MarkPaper) {
  return post('/api/kg/papers/unfavorite', token, { paper })
}

/** 记一次「点开看过」（同一篇后端会累加次数，不会重复插） */
export function recordView(token: string, paper: MarkPaper, topic?: string) {
  return post('/api/kg/papers/view', token, { paper, topic: topic ?? null })
}

/**
 * 登录 / 批量变动时把本地攒的收藏与观看一次性补到后端（幂等，可重复调用）。
 * replaceFavorites=true 表示「以后端这次收到的为准，多出来的删掉」——
 * 清空收藏夹、删掉整个空间时用，否则后端删不掉。
 */
export function syncMarks(
  token: string,
  favorites: MarkPaper[],
  views: MarkPaper[],
  replaceFavorites = false
) {
  return post('/api/kg/papers/sync', token, { favorites, views, replace_favorites: replaceFavorites })
}
