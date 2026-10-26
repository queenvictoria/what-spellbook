import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': new URL('./app', import.meta.url).pathname },
  },
  server: {
    // The API allows this dev origin explicitly, so the front end calls the API
    // directly rather than proxying. A proxy would hide the CORS setup from the
    // dev loop and only fail in a real deployment.
    //
    // The port is overridable because more than one copy of this dev server may be
    // running on the same machine; the API's CORS list follows FRONTEND_PORT, so a
    // second instance needs both set to the same value.
    port: Number(process.env.VITE_PORT) || 5173,
  },
})
