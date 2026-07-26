# Yav 个人影片磁链图书馆

Yav 是一个个人本地影片图书馆，核心目标是从多个来源收集、保存和浏览影片磁链。

当前来源只有 JavDB 和 JPHOO，后续可以继续增加。不同资源站提供的信息和资源可能不完整，因此 Yav 会按影片名归并同一影片，并让多个来源互相补充磁链和基础资料。

> 本项目不包含下载器，也不会自动下载影片。

## V2 项目范围

每部影片只管理以下内容：

- 影片名
- 封面（可缺失）
- 厂商（可缺失）
- 系列（可缺失）
- 女演员（可缺失、可多人）
- 日期（可缺失）
- 时长（可缺失）
- 收藏状态
- 各个来源发现的磁链

项目核心是磁链。封面和其他资料只用于浏览、筛选和识别影片，不要求每个来源都能提供完整信息。

## 核心规则

- 同一影片可以关联 JavDB、JPHOO 和未来其他来源。
- 影片优先按标准化影片名归并；信息明显冲突时不自动合并。
- 普通资料采用“补空不覆盖”：已有值默认保留，缺失值由其他来源补充。
- 女演员信息合并去重。
- 用户手动修改的资料不被自动扫描覆盖。
- 磁链按 BTIH 去重，新磁链只追加，不覆盖旧磁链。
- 每条磁链保留来源名称、来源网页、文件大小和发现时间。
- SQLite 是唯一业务数据源；CSV 和 Excel 仅用于旧数据迁移或导出。

## 图书馆界面

图书馆支持：

- 按影片名搜索
- 按厂商、系列、女演员组合筛选
- 按来源筛选
- 只看收藏
- 只看有磁链或无磁链
- “未知厂商”“未分类系列”“未知女演员”入口
- 海报墙、收藏架、资料册三种结构视图
- 分页浏览，不限制只显示前 60 部
- 影片详情与手动资料编辑
- 按来源展示同一 BTIH 的来源页面
- 复制磁链和打开来源网页

三种视图共用同一套视觉语言，变化的是布局和信息密度，不是简单换色主题。

## V2 开发启动

```powershell
cd "G:\Antigravity\Yav_Downing-v2"
python -m backend.app
```

访问 `http://127.0.0.1:8765`。

服务只监听 `127.0.0.1`，SQLite 默认保存在 `%LOCALAPPDATA%\Yav\v2\library.db`，不写入仓库。

## V1 数据迁移

迁移命令默认只演练，不修改新数据库：

```powershell
python -m backend.migrate_v1 `
  --old-db "旧版 library.db" `
  --new-db "新版 library.db"
```

确认统计后增加 `--apply` 才实际写入。


## V2 数据备份

备份只读取原数据库和本地封面文件，不会修改原数据，也不会覆盖已有备份。默认备份目录是 `%LOCALAPPDATA%\Yav\v2\backups`：

```powershell
python -m backend.backup `
  --data-dir "$env:LOCALAPPDATA\Yav\v2"
```

也可使用自定义备份位置：

```powershell
python -m backend.backup `
  --data-dir "$env:LOCALAPPDATA\Yav\v2" `
  --output-dir "D:\Yav-Backups"
```

每个备份目录包含 `library.db`、存在的本地封面副本，以及 `manifest.json`。远程封面网址保留在数据库中，不会重复下载。

## Windows 打包

在已安装 Python 和项目依赖的开发电脑上执行：

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean yav_v2.spec
```

生成文件为 `dist\Yav-V2.exe`。双击会启动本地服务并打开默认浏览器；业务数据仍保存于 `%LOCALAPPDATA%\Yav\v2`，不会写入 exe 所在目录。验收或排障可使用 `Yav-V2.exe --no-browser --port 8876`。
## 分支说明

- `v1-frozen`：旧版冻结基线，不再增加功能。
- `main`：当前旧版主分支，在 V2 完成前保持稳定。
- `v2-rebuild`：新版图书馆开发分支。

V1 的现有代码和研究记录仍保留在仓库中，供迁移 JavDB/JPHOO 抓取逻辑时参考。

## V2 文档

- [开发计划](docs/PLAN.md)
- [当前状态](docs/STATUS.md)
- [工作日志](docs/WORKLOG.md)
- [AI/开发约束](AGENTS.md)

## JPHOO 来源扫描

在左侧导航打开“来源管理”，在 JPHOO 区域配置系列。首次使用时点击“打开登录窗口”，只在 Yav V2 专用 Edge 中手动登录；登录完成后点击“验证登录”；显示 ready 后可执行全量扫描或继续扫描。扫描期间关闭会话或退出程序会先安全停止扫描，再释放浏览器 Profile。登录资料保存在 `%LOCALAPPDATA%\Yav\v2\browser-profile\jphoo`，不会提交到仓库。

## Windows 使用

发布版支持 --data-dir、--port、--no-browser、--backup、--restore、--migrate-v1 和 --dry-run。详见 [Windows 安装](docs/INSTALL_WINDOWS.md)、[V1 迁移](docs/MIGRATE_V1_TO_V2.md)、[备份恢复](docs/BACKUP_RESTORE.md) 和 [发布清单](docs/RELEASE_CHECKLIST.md)。

## RC2 安全退出

关闭浏览器不会退出 Yav。请使用页面中的“安全退出 Yav”或 `Yav-V2.exe --shutdown`；两者都会停止扫描并释放本地端口、锁和临时运行凭据。RC1 因缺少正常退出入口未完成单实例验收；RC2 已完成打包版 CLI 退出验证。JPHOO 打包版真实登录与扫描仍是发布阻塞项。

## RC4 安全退出与临时运行文件

关闭浏览器不会退出 Yav。请使用页面的“安全退出 Yav”，或执行 `Yav-V2.exe --shutdown`。运行期间，Yav 在数据目录的 `runtime\` 下原子写入实例信息和一次性关闭凭据；正常退出会删除它们。这个目录不包含业务数据，备份、恢复和 Git 都会忽略它。