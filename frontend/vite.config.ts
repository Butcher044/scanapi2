import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8090',
        /* Deliberately NOT changeOrigin. The API rejects writes whose `Origin`
           does not match `Host` (app/web_auth.py `_same_origin`), and rewriting
           Host to the target while the browser still sends the dev-server
           Origin makes every POST — login included — fail with 403.
           In production the SPA is served by the same app, so there is no proxy. */
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
  },
})
