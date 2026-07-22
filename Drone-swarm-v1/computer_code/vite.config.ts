import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Where the Python backend (Flask + Socket.IO) runs during development.
// Override with VITE_BACKEND_PROXY if you changed the backend port.
const backendTarget = process.env.VITE_BACKEND_PROXY || 'http://localhost:3001'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin in the browser during dev: proxy the API + Socket.IO to the
    // backend so the frontend can use relative URLs exactly like in production.
    proxy: {
      '/socket.io': { target: backendTarget, ws: true, changeOrigin: true },
      '/api': { target: backendTarget, changeOrigin: true },
    },
  },
})
