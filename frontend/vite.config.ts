import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import path from 'path'

export default defineConfig({
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return
          }

          if (id.includes('react-syntax-highlighter')) {
            return 'syntax-highlighter-vendor'
          }

          if (id.includes('prismjs') || id.includes('refractor')) {
            return 'prism-vendor'
          }

          if (
            id.includes('react-markdown') ||
            id.includes('remark-') ||
            id.includes('rehype-') ||
            id.includes('/katex/')
          ) {
            return 'markdown-vendor'
          }

          if (id.includes('@xyflow')) {
            return 'xyflow-vendor'
          }

          if (id.includes('cytoscape-fcose') || id.includes('cytoscape-cose-bilkent')) {
            return 'cytoscape-layout-vendor'
          }

          if (id.includes('/bluebird/') || id.includes('/underscore/')) {
            return 'legacy-utils-vendor'
          }

          if (
            id.includes('/mammoth/') ||
            id.includes('/jszip/') ||
            id.includes('/xmlbuilder/') ||
            id.includes('/dingbat-to-unicode/') ||
            id.includes('/@xmldom/xmldom/') ||
            id.includes('/argparse/') ||
            id.includes('/path-is-absolute/') ||
            id.includes('/lop/') ||
            id.includes('/base64-js/')
          ) {
            return 'mammoth-vendor'
          }

          if (
            id.includes('layout-base') ||
            id.includes('cose-base') ||
            id.includes('/heap/')
          ) {
            return 'cytoscape-layout-core-vendor'
          }

          if (id.includes('cytoscape')) {
            return 'cytoscape-core-vendor'
          }

          if (id.includes('recharts') || id.includes('/d3-')) {
            return 'charts-vendor'
          }

          if (
            id.includes('/react/') ||
            id.includes('/react-dom/') ||
            id.includes('react-router') ||
            id.includes('@tanstack/react-query') ||
            id.includes('zustand')
          ) {
            return 'react-vendor'
          }
        },
      },
    },
  },
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
    allowedHosts: true, // Allow all hosts
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
