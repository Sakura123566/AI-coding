import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  // GitHub Pages 项目页子路径（仓库名 AI-coding）→ 资源与 /kg 链接自动带上前缀
  base: '/AI-coding/',
  plugins: [vue()],
  // 首屏提速：提前把这些大依赖预打包，避免 dev 首次打开时现场编译整库而卡顿。
  optimizeDeps: {
    include: ['element-plus', '@element-plus/icons-vue', 'echarts', 'pinia']
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    host: true
  }
})
