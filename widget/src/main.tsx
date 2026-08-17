import React from "react";
import { createRoot } from "react-dom/client";
import { UsageWidget } from "./UsageWidget";
import type { WidgetTheme } from "./types";

// 本地预览：Vite 的 publicDir 已指向仓库根的 data/，所以 /stats.json 可取最新数据。
//
// 按容器宽度排成矩阵，而不是只看一个宽度。组件的断点是容器查询而非视口，博客正文栏
// 常见宽度就在 560~760 之间，窄栏（380）要能退化得体，所以这三档都得一眼看到。
//
// 真正上博客时，把 dataUrl 换成你的 CDN 地址即可，例如：
//   https://cdn.jsdelivr.net/gh/<你>/<仓库>@main/data/stats.json
// 可用 ?w=380、?theme=dark、?week=2026-W33 只渲染一档，方便截图时贴紧宽度看细节。
const params = new URLSearchParams(location.search);
const only = Number(params.get("w")) || null;
const onlyTheme = params.get("theme") as WidgetTheme | null;
const onlyWeek = params.get("week") ?? undefined;

const WIDTHS = only ? [only] : [760, 560, 380];

function Band({ theme, bg }: { theme: WidgetTheme; bg: string }) {
  return (
    <div style={{ background: bg, padding: 32, display: "grid", gap: 32 }}>
      {WIDTHS.map((width) => (
        <div key={width} style={{ width, maxWidth: "100%" }}>
          <UsageWidget
            dataUrl="/stats.json"
            theme={theme}
            width={width}
            week={onlyWeek}
          />
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {onlyTheme !== "dark" && <Band theme="light" bg="#ffffff" />}
    {onlyTheme !== "light" && <Band theme="dark" bg="#0d1117" />}
  </React.StrictMode>,
);
