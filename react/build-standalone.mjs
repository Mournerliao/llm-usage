import { build } from "esbuild";
import { writeFileSync } from "fs";

// 把 React + UsageWidget + stats.json 全部打包进一个自包含 HTML，
// 用 file:// 直接打开即可渲染，不依赖任何服务器/网络。
const result = await build({
  entryPoints: ["standalone.tsx"],
  bundle: true,
  format: "iife",
  loader: { ".json": "json" },
  define: { "process.env.NODE_ENV": '"production"' },
  minify: true,
  write: false,
  logLevel: "info",
});

const js = result.outputFiles[0].text;
const html = `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ADE 用量组件 · 离线预览</title>
    <style>
      body {
        margin: 0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #f9fafb;
        padding: 24px;
      }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script>${js}</script>
  </body>
</html>`;

writeFileSync("standalone.html", html);
console.log(`standalone.html 已生成，${js.length} 字节（已内联 React + 数据与组件）`);
