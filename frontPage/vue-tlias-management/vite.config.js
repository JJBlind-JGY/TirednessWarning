import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        secure: false,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/face-api': {
        target: 'http://127.0.0.1:8081',
        secure: false,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/face-api/, ''),
      },
      '/eeg': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true
      },
      '/wss': {
        target: 'http://127.0.0.1:8081',
        changeOrigin: true,
        secure: false,
        ws: true
      }
    }
  }
})
