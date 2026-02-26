import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false, // Allow Vite to automatically try next port if 5173 is taken
    host: true, // Listen on all addresses including LAN and localhost
    open: false, // Don't auto-open browser
  },
  build: {
    // Optimize chunk splitting
    rollupOptions: {
      output: {
        manualChunks: {
          // Separate vendor chunks for better caching
          'react-vendor': ['react', 'react-dom'],
          'query-vendor': ['@tanstack/react-query'],
          'chart-vendor': ['recharts'],
          'syntax-highlighter': ['react-syntax-highlighter'],
        },
      },
    },
    // Increase chunk size warning limit for large libraries
    chunkSizeWarningLimit: 1000,
    // Enable source maps for production debugging (optional)
    sourcemap: false,
  },
})
