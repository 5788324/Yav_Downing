# Yav V2 发布检查清单

更新时间：2026-07-27

## 当前发布目标

当前基线是 `2.0.0-rc4`。下一版只处理单实例并行启动问题，版本为 `2.0.0-rc5`。

完成 RC5 和新 Windows 用户验收后，直接进入正式 `2.0.0` 发布，不再增加功能。

## 已完成

### 核心功能

- [x] V2 SQLite 资料库。
- [x] V1 只读迁移、dry-run 和幂等执行。
- [x] 海报墙、收藏架、资料册和组合筛选。
- [x] JavDB 扫描、停止和继续。
- [x] JPHOO 登录恢复、扫描、停止、继续和重启恢复。
- [x] JPHOO 停止后最终状态为 `stopped`。

### 数据保护

- [x] SQLite 快照备份。
- [x] 备份 manifest 和本地封面。
- [x] 恢复 dry-run。
- [x] 恢复前自动备份。
- [x] 恢复失败不覆盖当前数据。
- [x] 浏览器 Profile、Cookie 和 runtime 不进入备份。

### Windows 包

- [x] 单文件 `Yav-V2.exe`。
- [x] `--data-dir`、`--port`、`--no-browser`。
- [x] `--backup`、`--restore`、`--migrate-v1`、`--dry-run`。
- [x] 页面安全退出和 `--shutdown`。
- [x] 服务仅监听 `127.0.0.1`。
- [x] RC4 从仓库外临时目录启动。
- [x] RC4 页面/API、关闭、重启、备份、恢复和迁移验收。
- [x] RC4 真实 JPHOO 隔离 Profile 验收。

### 自动检查

- [x] `python -m compileall backend tests yav_v2.py`
- [x] `python -m unittest discover -s tests -v`
- [x] `node --check backend/static/app.js`
- [x] `git diff --check`
- [x] 当前测试数量：47 项。

## RC5 必须完成

- [ ] 单实例锁在整个进程生命周期内持续持有。
- [ ] 第一个实例尚未启动 HTTP 时，第二个实例不能清理其 runtime。
- [ ] 两个真实子进程同时启动时，只有一个监听服务。
- [ ] 第二实例正常退出或打开已有实例。
- [ ] 错误实例不能删除其他实例的 runtime 文件。
- [ ] 页面安全退出回归通过。
- [ ] CLI `--shutdown` 回归通过。
- [ ] 备份、恢复和 V1 迁移快速回归通过。
- [ ] JPHOO ready、扫描、停止和退出快速回归通过。
- [ ] 版本更新为 `2.0.0-rc5`。
- [ ] 生成 RC5 EXE、文件大小和 SHA-256。

## 最终人工验收

在同一台电脑新建 Windows 本地用户：

- [ ] 不安装 Python。
- [ ] 不复制源码。
- [ ] 只复制 RC5 发布目录。
- [ ] 空库启动成功。
- [ ] 首页和 API 正常。
- [ ] 第二次启动不产生第二个服务。
- [ ] 页面安全退出。
- [ ] 再次启动正常。
- [ ] JPHOO 专用 Edge 会话可以启动。

## 正式发布

- [ ] 合并 `v2-rebuild` 到 `main`。
- [ ] 从合并提交重新构建 `Yav-V2.exe`。
- [ ] 计算正式 SHA-256。
- [ ] 创建 `v2.0.0` 标签。
- [ ] 发布 EXE、校验值和使用说明。
- [ ] 保留 `v1-frozen`。

## 当前结论

RC4 本机验收已经通过，但尚未正式发布。当前唯一开发任务是 RC5 单实例并行启动加固；完成后只剩新 Windows 用户验收。
