/**
 * 后端入口（薄代理）。
 *
 * Sprint 7b 起应用组装迁移至 src/server.ts（分层结构，TypeScript）。
 * 编译为 dist/server.js；此文件保留以兼容：
 *  - package.json scripts（node dist/server.js）
 *  - scf_bootstrap.js（require("./dist/server")）
 * 仅 re-export createApp / main。
 */

import { createApp, main } from "./src/server";

export { createApp, main };

if (require.main === module) {
  main();
}
