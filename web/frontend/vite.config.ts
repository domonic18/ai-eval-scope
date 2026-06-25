import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import fs from "node:fs"
import path from "node:path"

// 版本号优先级：构建期注入(VITE_APP_VERSION，Jenkins/Docker ARG 传入) > VERSION 文件 > 默认 1.0.0。
// Jenkins 在构建时读取 VERSION 并拼接 BUILD_NUMBER 形成 a.b.c.<BUILD>，通过 --build-arg 注入。
const versionFile = path.resolve(__dirname, "../VERSION")
const appVersion =
  process.env.VITE_APP_VERSION ||
  (fs.existsSync(versionFile) ? fs.readFileSync(versionFile, "utf-8").trim() : "1.0.0")

// 后端在 :9000；开发期 /api 与 /health 经代理转发
export default defineConfig({
  plugins: [react()],
  define: {
    "import.meta.env.VITE_APP_VERSION": JSON.stringify(appVersion),
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:9000", changeOrigin: true },
      "/health": { target: "http://localhost:9000", changeOrigin: true },
    },
  },
})
