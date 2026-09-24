// 前后端契约类型 + 数据获取层
// 前端只调用 POST /api/research/run（以及 GET /api/health 用于探活），
// 不接触任何模型密钥 / MCP（由后端完成）。
//
// 契约以 docs/API_HANDOFF.md（字段已冻结）为准：
//   请求：{ "keyword": string, "limit": number }
//   成功：{
//     "status":"success", "keyword", "resolved_keyword":string|null,
//     "count":number, "papers":[{id,title,authors,year,abstract,url,source}],
//     "report":{...}|null, "report_error":string|null,
//     "warnings":string[], "message":string|null
//   }
//   失败：{ "status":"error", "error_code": string, "message": string }  （可能伴随 HTTP 200 或 5xx）
// 真实论文信息由后端经 MCP 检索生成；url / source / year / abstract / authors 均可能为空。

export const DEFAULT_LIMIT = 10

export interface Paper {
  id: string
  title: string
  authors: string[]
  year: number // 0 表示缺失，UI 显示「年份未知」
  abstract: string // '' 表示缺失，UI 显示「暂无摘要」
  url: string | null
  source: string // '' 表示缺失，UI 不显示来源标签
}

// 研究报告（导航报告）结构
export interface ReportTheme {
  name: string
  description: string
  paper_ids: string[]
}
export interface ReadingStep {
  step: number
  paper_ids: string[]
  reason: string
}
export interface ResearchReport {
  overview: string
  themes: ReportTheme[]
  research_trends: string[]
  reading_path: ReadingStep[]
  exploration_questions: string[]
  limitations: string
}

// 应用层归一化结果（与契约 success 负载对应）
export interface ResearchResponse {
  status: 'success'
  keyword: string
  resolvedKeyword: string | null
  count: number
  papers: Paper[]
  report: ResearchReport | null
  reportError: string | null
  warnings: string[]
  message: string | null
}

// 应用层错误：携带 error_code 与是否可重试，便于 UI 决定「给不给重试按钮」。
export class ResearchApiError extends Error {
  errorCode: string
  retryable: boolean
  httpStatus?: number
  constructor(message: string, errorCode: string, retryable: boolean, httpStatus?: number) {
    super(message)
    this.name = 'ResearchApiError'
    this.errorCode = errorCode
    this.retryable = retryable
    this.httpStatus = httpStatus
  }
}

// 后端错误码 → 是否可重试（依据 API_HANDOFF.md 第 4 节）
//   4xx（EMPTY_KEYWORD / INVALID_KEYWORD / INVALID_REQUEST）：输入问题，不自动重试
//   MCP_TIMEOUT / MCP_ERROR / INTERNAL_ERROR：后端/上游问题，可重试
function isRetryable(errorCode: string, httpStatus: number): boolean {
  if (['MCP_TIMEOUT', 'MCP_ERROR', 'INTERNAL_ERROR'].includes(errorCode)) return true
  if (errorCode.startsWith('HTTP_')) return httpStatus >= 500
  return false
}

// 后端错误码 → 兜底文案（优先用后端 message，这里只在 message 缺失时兜底）
function defaultMsgFor(errorCode: string): string {
  switch (errorCode) {
    case 'EMPTY_KEYWORD':
      return '请输入研究主题'
    case 'INVALID_KEYWORD':
      return '主题过长，请缩短后再试'
    case 'INVALID_REQUEST':
      return '请求参数有误，请检查输入'
    case 'MCP_TIMEOUT':
      return '论文检索服务暂时不可用（超时），请稍后重试'
    case 'MCP_ERROR':
      return '检索服务暂不可用，请重试'
    case 'INTERNAL_ERROR':
      return '服务内部错误，请重试'
    default:
      return '检索失败，请稍后重试'
  }
}

// 默认 mock：让「等后端」阶段的 UI 骨架也能直接演示。
// 接真实后端时把 VITE_USE_MOCK 置 'false' 即可切换，无需改 UI 代码。
const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'true') === 'true'

// 字段归一化：后端返回的字段名可能略有差异，这里统一成前端使用的字段。
function normalizePaper(p: any): Paper {
  return {
    id: String(p?.id ?? ''),
    title: String(p?.title ?? p?.titleZh ?? '未命名文献'),
    authors: Array.isArray(p?.authors)
      ? p.authors.map(String)
      : p?.author
        ? [String(p.author)]
        : [],
    // year 可能为 null → 归一成 0，UI 显示「年份未知」
    year: Number(p?.year ?? p?.publishedYear ?? p?.yearPublished ?? 0) || 0,
    abstract: String(p?.abstract ?? p?.summary ?? ''),
    // url 可能为 null（后端未拿到原文链接），保持可空，UI 层据此禁用外链
    url: p?.url ? String(p.url) : null,
    // source 可能为 null → 归一成 ''，UI 不显示来源标签
    source: p?.source ? String(p.source ?? p.venue ?? p.journal ?? p.publication) : ''
  }
}

function normalizeReport(r: any): ResearchReport | null {
  if (!r) return null
  return {
    overview: String(r?.overview ?? ''),
    themes: Array.isArray(r?.themes)
      ? r.themes.map((t: any) => ({
          name: String(t?.name ?? ''),
          description: String(t?.description ?? ''),
          paper_ids: Array.isArray(t?.paper_ids) ? t.paper_ids.map(String) : []
        }))
      : [],
    research_trends: Array.isArray(r?.research_trends)
      ? r.research_trends.map(String)
      : Array.isArray(r?.keyDirections)
        ? r.keyDirections.map(String)
        : [],
    reading_path: Array.isArray(r?.reading_path)
      ? r.reading_path.map((s: any) => ({
          step: Number(s?.step ?? 0) || 0,
          paper_ids: Array.isArray(s?.paper_ids) ? s.paper_ids.map(String) : [],
          reason: String(s?.reason ?? '')
        }))
      : [],
    exploration_questions: Array.isArray(r?.exploration_questions)
      ? r.exploration_questions.map(String)
      : [],
    limitations: String(r?.limitations ?? '')
  }
}

function normalizeResponse(data: any): ResearchResponse {
  const papers = Array.isArray(data.papers) ? data.papers.map(normalizePaper) : []
  return {
    status: 'success',
    keyword: String(data?.keyword ?? ''),
    resolvedKeyword: data?.resolved_keyword ? String(data.resolved_keyword) : null,
    count: Number(data?.count ?? papers.length) || 0,
    papers,
    report: normalizeReport(data?.report),
    reportError: data?.report_error ? String(data.report_error) : null,
    warnings: Array.isArray(data?.warnings) ? data.warnings.map(String) : [],
    message: data?.message ? String(data.message) : null
  }
}

export async function fetchResearch(
  keyword: string,
  limit: number = DEFAULT_LIMIT
): Promise<ResearchResponse> {
  if (USE_MOCK) {
    const { mockResearchForTopic } = await import('../mocks/research.mock')
    await new Promise((r) => setTimeout(r, 600))
    // 无后端时，用 mock 模拟「按主题命中 / 未命中」两种结果，方便演示 UI。
    // 真实的相关性检索与抓取由后端（MCP + 模型）负责，前端只呈现。
    return mockResearchForTopic(keyword, limit)
  }

  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/research/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keyword, limit })
    })
  } catch {
    // 网络层失败（后端没起来 / CORS / 断网），给出可读提示，不白屏
    throw new ResearchApiError(
      '连不上后端服务，请确认后端已启动（双击 start_backend.bat）',
      'NETWORK',
      true
    )
  }

  // 先尝试解析 body（后端多数错误也是 200 + JSON body）
  let raw: any = null
  let parseFailed = false
  try {
    raw = await res.json()
  } catch {
    parseFailed = true
  }

  // ① 契约失败态：body.status === 'error'（HTTP 可能是 200 也可能是 5xx）
  if (!parseFailed && raw && raw.status === 'error') {
    const code = raw.error_code ? String(raw.error_code) : `HTTP_${res.status}`
    const msg = typeof raw.message === 'string' && raw.message ? raw.message : defaultMsgFor(code)
    throw new ResearchApiError(msg, code, isRetryable(code, res.status), res.status)
  }

  // ② body 有 status 但不是 success/error 的未知状态
  if (!parseFailed && raw && raw.status && raw.status !== 'success') {
    throw new ResearchApiError('未知响应状态', 'UNKNOWN_STATUS', false, res.status)
  }

  // ③ 非 2xx 且 body 无法解析（如 502/504 网关返回的 HTML）
  if (!res.ok) {
    const code = `HTTP_${res.status}`
    const msg =
      res.status === 404
        ? '后端接口不存在（404），请检查路由是否为 /api/research/run'
        : res.status >= 500
          ? `后端暂时不可用（HTTP ${res.status}），请稍后重试`
          : `请求被拒绝（HTTP ${res.status}）`
    throw new ResearchApiError(msg, code, res.status >= 500, res.status)
  }

  // ④ body 解析失败但 HTTP 正常（理论上不该发生）
  if (parseFailed) {
    throw new ResearchApiError('后端返回的内容无法解析，请联系后端确认格式', 'BAD_RESPONSE', false, res.status)
  }

  // ⑤ 成功路径
  return normalizeResponse(raw)
}

// 探活：GET /api/health，仅返回是否可达（不抛异常）
export async function pingHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/health`, { method: 'GET' })
    return res.ok
  } catch {
    return false
  }
}
