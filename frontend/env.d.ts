/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_MODE?: 'demo' | 'backend'
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
