import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
    proxy: {
      '/auth': 'http://127.0.0.1:8001',
      '/sellers': 'http://127.0.0.1:8001',
      '/tasks': 'http://127.0.0.1:8001',
      '/collections': 'http://127.0.0.1:8001',
      '/hashtag-groups': 'http://127.0.0.1:8001',
      '/hashtags': 'http://127.0.0.1:8001',
      '/analytics': 'http://127.0.0.1:8001',
      '/reminders': 'http://127.0.0.1:8001',
      '/dashboard/kanban': 'http://127.0.0.1:8001',
      '/dashboard/calendar': 'http://127.0.0.1:8001',
      '/media': 'http://127.0.0.1:8001'
    }
  }
})
