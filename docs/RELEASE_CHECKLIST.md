# Yav V2 发布检查清单

更新时间：2026-07-27

## 当前发布目标

RC5 代码已经完成。下一步只做本机完整回归、RC5 构建和新 Windows 用户验收；通过后直接发布正式 `2.0.0`，不再增加功能。

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

### RC5 单实例修复

- [x] 单实例锁在整个进程生命周期内持续持有。
- [x] 第一个实例尚未启动 HTTP 时，第二个实例不能清理其 runtime。
- [x] 第二实例会等待首个实例完成启动并读取实际端口。
- [x] 错误实例不能删除其他实例的 runtime 文件。
- [x] 两个真实 Python 子进程同时竞争时只有一个取得锁。
- [x] 版本更新为 `2.0.0-rc5`。
- [x] 新增 4 项锁测试并在隔离环境通过。

## RC5 本机必须完成

### 自动检查

- [ ] `python -m compileall backend tests yav_v2.py`
- [ ] `python -m unittest discover -s tests -v`
- [ ] `node --check backend/static/app.js`
- [ ] `git diff --check`
- [ ] 确认完整测试总数和全部结果。

### 构建与运行

- [ ] 构建 `release\Yav-V2-2.0.0-rc5\Yav-V2.exe`。
- [ ] 记录 RC5 EXE 文件大小和 SHA-256。
- [ ] 同时启动两个 RC5 EXE，确认只有一个实际监听服务。
- [ ] 第二实例正常退出或打开已有实例。
- [ ] 页面安全退出回归通过。
- [ ] CLI `--shutdown` 回归通过。
- [ ] 退出后进程、端口、实例信息和关闭凭据全部释放。

### 功能快速回归

- [ ] 备份、恢复和 V1 迁移通过。
- [ ] JPHOO ready、扫描、停止和退出通过。

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

RC5 的代码和针对性并发测试已经完成；尚未完成本机完整测试、Windows 构建和最终人工验收，因此不能标记正式发布。
