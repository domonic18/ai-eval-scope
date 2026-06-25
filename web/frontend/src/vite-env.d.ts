/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 应用版本号：构建期由 vite.config.ts 的 define 注入（a.b.c 来自 VERSION，第 4 段为 Jenkins 构建号）。 */
  readonly VITE_APP_VERSION: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
