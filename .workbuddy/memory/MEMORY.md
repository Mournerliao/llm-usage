# 项目长期笔记

## WorkBuddy 用量接入（2026-08-16 确认）
- 数据源：`~/.workbuddy/workbuddy.db`（WorkBuddy 自身运行库，只读）。
  - `session_usage`：session_id, used(累计消耗), size(=192000 疑似配额上限), updated_at(ms)
  - `sessions`：id, model(如 hy3), cwd, created_at(ms), title, deleted_at
  - JOIN：session_usage.session_id = sessions.id
- 已实现：`collectors/workbuddy.py`（local 模式；跨平台探测路径；只读 URI 连接 + PRAGMA busy_timeout 规避运行锁）。
  - 映射：model←sessions.model；date←created_at 本地日；total←used（无 in/out 拆分，整体计入 input_tokens；因为 Record.to_dict 不含 total_tokens 属性，必须落到 input/output 上）；requests=1/会话。
- 其他方法实测不可行 / 需特定版本：
  - 本地 HTTP API 127.0.0.1:8080：当前桌面版走 named pipe，不监听 TCP，连不上。
  - quota 日志 %APPDATA%/WorkBuddy/logs/quota：目录不存在。
  - traces 文件：含 trace.totalTokens，但为调试数据、不稳定。
  - 官方 REST /api/v1/stats：CodeBuddy Code CLI v2.84+ 才有，桌面版未暴露。
  - 企业 OpenAPI api.copilot.tencent.com：需企业旗舰版 + enterpriseId + Bearer，最全（成员/模型/credit 明细），可走 cloud 模式。
- 同次关键修复：
  - `run.py`：`yaml.safe_load(CFG_PATH)` → `yaml.safe_load(CFG_PATH.read_text(...))`（Path 不能直接给 safe_load，否则 cloud 模式在 Action 也崩）。
  - config type：`workbuddy_local`/`cursor_local` → `workbuddy`/`cursor`（对齐 run.py LOCAL_SIDE 键，否则 local 源静默跳过）。
  - `.gitignore` 已移除 `data/local/`，允许本地采集数据提交回流。
- 备注：stats.json 原假数据已被真实 workbuddy 数据覆盖（local 模式跑通后）。
- 依赖未装时 `run.py` 会缺 yaml：用 managed python venv（`C:/Users/win/.workbuddy/binaries/python/envs/ade/Scripts/python.exe`）或 `pip install -r requirements.txt` 后运行。
