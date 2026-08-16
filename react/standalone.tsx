import { createRoot } from "react-dom/client";
import { UsageWidget } from "./src/UsageWidget";
// 直接把仓库根的 stats.json 打进包里，离线也能渲染（无需服务器）
// @ts-ignore
import stats from "../data/stats.json";

createRoot(document.getElementById("root")!).render(<UsageWidget data={stats} />);
