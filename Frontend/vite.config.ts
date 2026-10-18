import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    open: true,
    // Prevent caching of index.html so users always get fresh script URLs after deploy (avoids blank page)
    headers: {
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      Pragma: 'no-cache',
      Expires: '0',
    },
  },
  build: {
    outDir: 'build',
    // Content hashes bust browser/CDN cache after each deploy. Without them, assets/index.css keeps the
    // same URL and real devices often keep serving stale CSS (DevTools “Disable cache” hides this).
    // Ensure production serves index.html with short cache (or no-cache) so clients pick up new hashed URLs.
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
})
