# Yav 当前状态

更新时间：2026-07-27

## 当前结论

**Yav 2.0.0 已正式发布。**

- 正式分支：`main`
- 正式标签：`v2.0.0`
- Windows 文件：`Yav-V2.exe`
- EXE 大小：55,196,090 bytes
- SHA-256：`E801B5201C81625863DC5853088B6BB76401DA53590A24EEE97770975CA6021C`

正式发布资产已从 GitHub Release 重新下载并复算 SHA-256，结果与发布的 `SHA256SUMS.txt` 一致。

## 已完成

- SQLite 资料库与海报墙、收藏架、资料册。
- JavDB、JPHOO 扫描、停止、继续和重启恢复。
- JPHOO 独立 Edge Profile 与登录复用。
- V1 只读迁移、dry-run 和幂等执行。
- SQLite 快照备份、安全恢复和恢复前自动备份。
- 页面安全退出与 `Yav-V2.exe --shutdown`。
- 生命周期单实例锁和并行启动保护。
- 日志轮转和敏感信息脱敏。
- PyInstaller 单文件 Windows EXE。

## 验收结果

完整测试已在以下干净环境通过：

- Ubuntu + Python 3.11
- Ubuntu + Python 3.12
- Windows + Python 3.11
- Windows + Python 3.12

干净 Windows 打包验收已通过：

- 隔离 PATH 启动，不依赖外部 Python；
- 首页、状态与筛选 API；
- 仅监听 `127.0.0.1`；
- 打包版 Playwright 启动系统 Edge；
- 页面和 CLI 安全退出；
- 退出后进程、端口、Edge 与 runtime 全部释放；
- 备份、恢复、V1 迁移与 SQLite 完整性检查；
- 日志未发现完整磁链、Cookie、授权信息或关闭令牌。

验收报告：`FINAL_ACCEPTANCE_SUCCESS`

## 分支与维护

- `main`：Yav 2.x 正式主分支。
- `v1-frozen`：V1 永久冻结基线。
- `v2-rebuild`：保留 V2 重建历史，不再作为日常发布主线。

2.0.0 发布后只处理真实使用中发现的缺陷，不继续预设发布门槛或增加计划外功能。
