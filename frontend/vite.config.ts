import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import path from 'path'

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  plugins: [
    react({
      typescript: false
    }),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'apple-touch-icon.png', 'masked-icon.svg'],
      manifest: {
        name: 'Sara - Personal AI Hub',
        short_name: 'Sara Hub',
        description: 'Your personal AI assistant and knowledge management system',
        theme_color: '#6366f1',
        background_color: '#ffffff',
        display: 'standalone',
        icons: [
          {
            src: 'pwa-192x192.png',
            sizes: '192x192',
            type: 'image/png'
          },
          {
            src: 'pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png'
          }
        ]
      }
    })
  ],
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
    allowedHosts: (process.env.VITE_ALLOWED_HOSTS || 'sara.avery.cloud,localhost')
      .split(',')
      .map(h => h.trim())
      .filter(Boolean),
    // Allow overriding HMR host from env; otherwise let Vite infer
    hmr: process.env.VITE_HMR_HOST ? { host: process.env.VITE_HMR_HOST } : undefined
  },
  define: {
    global: 'globalThis',
  },
  preview: {
    host: '0.0.0.0',
    port: 3000
  }
})
