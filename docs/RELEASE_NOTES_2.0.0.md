# Yav 2.0.0

Yav 2.0.0 是一次完整重建：从旧版抓取工具转为本机 SQLite 影片磁链资料馆。

## 主要功能

- 海报墙、收藏架、资料册三种浏览方式。
- 按影片名、厂商、系列、女演员、来源、收藏和磁链状态筛选。
- JavDB 与 JPHOO 来源扫描。
- JPHOO 独立 Edge Profile、登录复用、停止、继续和重启恢复。
- 同一影片可关联多个来源。
- 磁链按 BTIH 去重，并保留多个来源页面。
- 用户手工编辑字段不被自动扫描覆盖。

## 数据保护

- SQLite 是唯一业务数据源。
- V1 数据库只读迁移。
- 迁移与恢复支持 `--dry-run`。
- SQLite 原生快照备份。
- 恢复前自动备份当前 V2 数据。
- 恢复失败不会覆盖当前资料库。
- 浏览器 Profile、Cookie、日志和运行凭据不进入备份。

## Windows 运行

- 单文件 `Yav-V2.exe`。
- 默认数据目录：`%LOCALAPPDATA%\Yav\v2`。
- 服务只监听 `127.0.0.1`。
- 生命周期单实例锁，防止并行启动破坏运行状态。
- 页面中的“安全退出 Yav”和 `Yav-V2.exe --shutdown` 会停止扫描并释放 Edge、端口和运行锁。

## 常用命令

```powershell
Yav-V2.exe --backup
Yav-V2.exe --restore "备份目录" --dry-run
Yav-V2.exe --restore "备份目录"
Yav-V2.exe --migrate-v1 "旧版 library.db" --dry-run
Yav-V2.exe --migrate-v1 "旧版 library.db"
Yav-V2.exe --shutdown
```

## 验收

2.0.0 发布前已在以下环境执行完整测试：

- Ubuntu + Python 3.11 / 3.12
- Windows + Python 3.11 / 3.12

并在干净 Windows runner 中完成单文件 EXE 的启动、系统 Edge、页面与 CLI 退出、备份恢复、V1 幂等迁移、SQLite 完整性和日志脱敏验收。

## 升级说明

V1 用户先备份旧数据库，然后使用：

```powershell
Yav-V2.exe --migrate-v1 "旧版 library.db" --dry-run
```

确认统计后再执行正式迁移。V1 数据库始终以只读方式打开。

## 不包含

本版本不包含下载器、播放器、云同步、用户账号、远程服务或推荐系统。
