// 周报服务层（前后端契约）。默认走 mock（VITE_USE_MOCK 未显式置 'false' 即为 mock）。
//
// 约定端点：
//   GET  /api/reports/weekly      (Bearer, ?week_start=&refresh=) -> ok(week_start, week_end, report, cached)
//   GET  /api/reports/weekly.pdf  (Bearer) -> PDF 二进制（Content-Disposition: attachment; filename*=UTF-8''...）
//
// 注意：PDF 需要 Bearer 鉴权，必须用 fetch 带 token 取 blob，不能用裸 <a href>。

import { type WeeklyReport } from '../types/user'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
// 默认 mock：让「等后端」阶段的 UI 骨架也能直接演示。
const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'true') === 'true'

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

// 后端统一成功包 { status:'success', ... }；错误 { status:'error', error_code, message }
async function parseJson(res: Response): Promise<any> {
  const data = await res.json().catch(() => ({}))
  if (data?.status === 'error' || (!res.ok && data?.status !== 'success')) {
    throw new Error(data?.message || `请求失败（HTTP ${res.status}）`)
  }
  return data
}

const authHeaders = (token: string) => ({ Authorization: `Bearer ${token}` })

// —— mock 兜底 ——
const MOCK_REPORT: WeeklyReport = {
  week_start: '2026-09-15',
  week_end: '2026-09-21',
  cached: false,
  report: {
    summary: '本周你围绕图神经网络与检索增强生成做了深入探索，整体活跃度稳定上升。',
    highlights: [
      { topic: '图神经网络', papers: 4, trend: 'up' },
      { topic: '检索增强生成', papers: 3, trend: 'flat' },
      { topic: '对比学习', papers: 2, trend: 'down' }
    ],
    total_searches: 8,
    total_messages: 23,
    active_days: 5,
    top_keywords: ['图神经网络', '检索增强生成', '对比学习']
  }
}

// —— 读取周报（JSON）——
export async function getWeeklyReport(
  token: string,
  opts?: { week_start?: string; refresh?: boolean }
): Promise<WeeklyReport> {
  if (USE_MOCK) {
    await delay(400)
    return JSON.parse(JSON.stringify(MOCK_REPORT))
  }
  const params = new URLSearchParams()
  if (opts?.week_start) params.set('week_start', opts.week_start)
  if (opts?.refresh) params.set('refresh', '1')
  const qs = params.toString()
  const res = await fetch(`${API_BASE}/api/reports/weekly${qs ? '?' + qs : ''}`, {
    headers: authHeaders(token)
  })
  const data = await parseJson(res)
  return {
    week_start: data.week_start,
    week_end: data.week_end,
    report: data.report,
    cached: !!data.cached
  }
}

// —— 下载周报（PDF 二进制）——
export async function downloadWeeklyReportPdf(token: string): Promise<Blob> {
  if (USE_MOCK) {
    await delay(300)
    return buildMockPdf(MOCK_REPORT)
  }
  const res = await fetch(`${API_BASE}/api/reports/weekly.pdf`, { headers: authHeaders(token) })
  if (!res.ok) {
    throw new Error(`PDF 下载失败（HTTP ${res.status}）`)
  }
  return await res.blob()
}

// 从响应头 Content-Disposition 提取文件名（兼容 filename*=UTF-8'' 形式）
export function pdfFilenameFromResponse(res: Response, fallback = 'weekly-report.pdf'): string {
  const cd = res.headers.get('Content-Disposition') || ''
  const star = cd.match(/filename\*=UTF-8''([^;]+)/i)
  if (star) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      /* ignore */
    }
  }
  const plain = cd.match(/filename="?([^";]+)"?/i)
  if (plain) return plain[1].trim()
  return fallback
}

// —— 生成最小可用 PDF（mock 演示用，内容以 ASCII 为主保证可读）——
function buildMockPdf(rep: WeeklyReport): Blob {
  const lines: string[] = []
  lines.push('Knowledge Party - Weekly Report')
  lines.push(`Period: ${rep.week_start} ~ ${rep.week_end}`)
  lines.push('')
  const r = rep.report as Record<string, any>
  if (r?.summary) {
    lines.push('Summary:')
    lines.push(limitAscii(String(r.summary)))
    lines.push('')
  }
  if (typeof r?.total_searches === 'number') lines.push(`Total searches: ${r.total_searches}`)
  if (typeof r?.total_messages === 'number') lines.push(`Total messages: ${r.total_messages}`)
  if (typeof r?.active_days === 'number') lines.push(`Active days: ${r.active_days}`)
  lines.push('')
  lines.push('(This is a mock PDF. Connect the backend for a full CJK report.)')
  return makePdf(lines)
}

function limitAscii(s: string): string {
  // PDF 基础字体不含中文字形，mock 演示仅保留 ASCII，中文以 [..] 占位避免乱码。
  return s.replace(/[^\x20-\x7E]/g, (ch) => `[${ch}]`)
}

function makePdf(lines: string[]): Blob {
  const escape = (s: string) => s.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)')
  const content = lines
    .map((l, i) => `BT /F1 11 Tf 50 ${780 - i * 16} Td (${escape(l)}) Tj ET`)
    .join('\n')
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'
  ]
  let pdf = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((obj, idx) => {
    offsets.push(pdf.length)
    pdf += `${idx + 1} 0 obj\n${obj}\nendobj\n`
  })
  const xrefStart = pdf.length
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  offsets.forEach((off) => {
    pdf += String(off).padStart(10, '0') + ' 00000 n \n'
  })
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`
  return new Blob([pdf], { type: 'application/pdf' })
}
