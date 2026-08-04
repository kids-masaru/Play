import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  base: '/Play/',
  // UI確認モードでは大容量の公開CSVコピーを省き、高速にバンドルだけ検証する。
  publicDir: mode === 'check' ? false : 'public',
  plugins: [react()],
  server: {
    fs: {
      // daily_dataフォルダにアクセスできるように許可
      allow: ['..']
    }
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
}))
