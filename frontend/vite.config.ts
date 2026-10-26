import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': new URL('./app', import.meta.url).pathname },
  },
  server: {
    // The API allows this dev origin explicitly, so the front end calls :8000
    // directly rather than proxying. A proxy would hide the CORS setup from the
    // dev loop and only fail in a real deployment.
    port: 5173,
  },
})
