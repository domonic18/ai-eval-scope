import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

// 后端在 :9000；开发期 /api 与 /health 经代理转发
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:9000", changeOrigin: true },
      "/health": { target: "http://localhost:9000", changeOrigin: true },
    },
  },
})
