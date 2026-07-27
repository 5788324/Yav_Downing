# Yav 当前状态

更新时间：2026-07-27

## 当前结论

Yav 2.0.0 的功能开发和发布候选验收已经完成。版本号已切换为 `2.0.0`，当前正在执行正式合并、Windows 构建、标签和 GitHub Release 发布。

## 已完成

- SQLite 资料库与三种浏览视图。
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

## 正式发布流程

```text
版本切换为 2.0.0
→ 合并 v2-rebuild 到 main
→ 干净 Windows runner 重新测试和构建
→ 生成 SHA256SUMS.txt
→ 创建 v2.0.0 标签和 GitHub Release
```

## 发布后原则

- `main` 作为 Yav 2.x 正式主分支。
- `v1-frozen` 永久保留。
- 不在 2.0.0 发布链路中新增功能。
- 仅针对真实使用中发现的缺陷安排修复版本。
