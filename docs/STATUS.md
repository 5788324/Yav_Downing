# Yav V2 当前状态

更新时间：2026-07-27

## 一句话结论

Yav V2 的主要功能已经完成。RC5 的单实例并发修复已经写入 `v2-rebuild`，现在只剩本机完整回归、RC5 构建和新 Windows 用户验收。

## 当前基线

- 分支：`v2-rebuild`
- 代码版本：`2.0.0-rc5`
- 已发布验证的本地包仍是 RC4。
- RC4 包：`release\Yav-V2-2.0.0-rc4\Yav-V2.exe`
- RC4 SHA-256：`4580E84B5611D91BD3A50B0D9329B2A458A73878C6BB2F730C143B11827111A1`
- RC5 包尚未构建，因此没有 RC5 SHA-256。

## 已完成

### 资料库与界面

- SQLite 是唯一业务数据源。
- 支持影片、演员、来源页面、磁链、收藏和手工资料。
- 磁链按 BTIH 去重，同一磁链保留多个来源。
- 支持海报墙、收藏架、资料册、搜索、组合筛选、详情和编辑。
- V1 可只读迁移到 V2，支持 dry-run 和重复执行。

### 来源扫描

- JavDB：全量扫描、继续、停止、进度和磁链写入。
- JPHOO：统一 Edge Profile、登录恢复、扫描、停止、继续和重启恢复。
- 扫描中退出会先停止扫描，再释放浏览器和 Profile。
- JPHOO 停止后最终状态为 `stopped`，不会误报 `failed`。

### 数据保护与发布入口

- 数据库快照、本地封面和 manifest 备份。
- 校验、dry-run、恢复前自动备份和失败保护。
- 单文件 `Yav-V2.exe`。
- 页面安全退出和 `Yav-V2.exe --shutdown`。
- 服务只监听 `127.0.0.1`。
- RC4 已完成本机隔离启动、关闭、重启、备份、恢复、迁移和真实 JPHOO 扫描验收。

## 本轮 RC5 已完成

- 单实例锁改为进程生命周期内持续持有的操作系统文件锁。
- 第二个启动器不能删除第一个正在启动实例的 `instance.json` 和关闭凭据。
- 第二个启动器会等待现有实例完成启动，再打开已有页面或提示正在启动。
- 释放旧锁时会校验 instance ID，不会删除其他实例的运行状态。
- Windows 正常退出后会清理锁载体；如果新实例已打开锁文件，则保留文件而不破坏新实例。
- 新增 4 项锁测试：
  - 活跃锁不能被第二实例替换；
  - 无持有者的陈旧锁可以复用；
  - 旧实例不能删除其他实例状态；
  - 两个真实子进程同时竞争时只有一个取得锁。

相关提交：

- `8f034e4 fix: hold Yav instance lock for process lifetime`
- `18076d4 fix: wait for the existing Yav instance safely`
- `d74edf4 test: cover concurrent Yav instance locking`
- `33ffb60 fix: clean Windows lock carrier after shutdown`

## 已完成的验证

- `backend/runtime.py` 语法检查通过。
- `yav_v2.py` 语法检查通过。
- 新增的 4 项并发锁测试在隔离环境中通过。

## 尚未完成

### 本机 RC5 回归

需要在项目电脑执行：

- 全套 Python 单元测试；
- JavaScript 语法检查；
- Git 空白检查；
- PyInstaller 构建；
- 两个 RC5 EXE 同时启动，确认只有一个实际监听服务；
- 页面退出和 CLI 退出；
- 备份、恢复、迁移和 JPHOO 快速回归。

### 新 Windows 用户验收

在同一台电脑新建 Windows 本地用户，只复制 RC5 发布包，不安装 Python、不复制源码，验证：

- 空库启动；
- 页面和 API；
- 第二次启动不会产生第二个服务；
- 安全退出和重启；
- 系统 Edge 可以被 JPHOO 会话启动。

## 发布路线

```text
RC5 代码完成
→ 本机完整测试和 RC5 构建
→ RC5 并行启动验收
→ 新 Windows 用户验收
→ 合并 main
→ 构建正式 2.0.0
→ 创建 v2.0.0 标签
```

## 明确不做

发布前不再增加新资源站、下载器、播放器、云同步、账号系统、复杂安全平台或大规模 UI 重做。

## 发布判断

当前判断：**RC5 代码已完成，尚未构建和正式验收。**
