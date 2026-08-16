import React from "react";
import { createRoot } from "react-dom/client";
import { UsageWidget } from "./UsageWidget";

// 本地预览：Vite 的 publicDir 已指向仓库根的 data/，所以 /stats.json 可取最新数据。
// 真正上博客时，把 dataUrl 换成你的 CDN 地址即可，例如：
//   https://cdn.jsdelivr.net/gh/<你>/<仓库>@main/data/stats.json
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <div style={{ padding: 24, background: "#F9FAFB", minHeight: "100vh" }}>
      <UsageWidget dataUrl="/stats.json" />
    </div>
  </React.StrictMode>
);
