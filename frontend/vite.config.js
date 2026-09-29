import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // maplibre-gl 6 loads its web worker via new URL(<name>, import.meta.url); pre-bundling moves the
  // module into .vite/deps, away from the worker file, and the map stays blank. Serve it as-is.
  optimizeDeps: { exclude: ['maplibre-gl'] },
  worker: { format: 'es' },   // MapLibre starts its worker as a module worker (setWorkerUrl in MapView)
  server: {
    host: true,
    port: 5173,
    watch: { usePolling: true }, // bind-mounted from macOS; inotify events don't cross the VM
  },
})
