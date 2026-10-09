import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// During development the React app runs on :5173 and forwards every /api call
// to the FastAPI server on :8000, so the browser sees a single origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://localhost:8000' },
  },
})
