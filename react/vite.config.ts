import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = fileURLToPath(new URL("..", import.meta.url));

// 本地预览时，让 Vite 直接读取仓库根的 data/ 目录，
// 这样 /stats.json 就能取到 aggregate.py 生成的最新数据，所见即所得。
export default defineConfig({
  plugins: [react(), tailwindcss()],
  publicDir: resolve(rootDir, "data"),
  server: {
    port: 5173,
    open: true,
  },
});
