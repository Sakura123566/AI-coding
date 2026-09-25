export type AppMode = 'demo' | 'backend'

const env = (import.meta as any).env || {}
const rawMode = String(env.VITE_APP_MODE || '').toLowerCase()

export const appMode: AppMode = rawMode === 'backend' ? 'backend' : 'demo'
export const isDemoMode = appMode === 'demo'
export const isBackendMode = appMode === 'backend'
export const apiBase = String(env.VITE_API_BASE_URL || '').replace(/\/$/, '')

export const configError =
  isBackendMode && !apiBase
    ? '当前构建声明为 backend 模式，但没有配置 VITE_API_BASE_URL。'
    : ''

export function backendUrl(path: string): string {
  if (configError) throw new Error(configError)
  if (!path.startsWith('/')) return `${apiBase}/${path}`
  return `${apiBase}${path}`
}