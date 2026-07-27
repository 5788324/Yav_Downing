# Yav 2.0

Yav 是一个仅在本机运行的个人影片磁链资料馆，用于收集、整理和浏览 JavDB、JPHOO 等来源中的影片资料与磁链。

> Yav 不包含下载器、播放器、云同步或账号系统，也不会自动下载影片。

## 主要能力

- SQLite 是唯一业务数据源。
- 海报墙、收藏架、资料册三种视图。
- 按影片名、厂商、系列、女演员、来源、收藏和磁链状态筛选。
- 同一影片可关联多个来源。
- 磁链按 BTIH 去重，并保留多个来源页面。
- 手工编辑的资料不会被后续扫描覆盖。
- JavDB 与 JPHOO 支持扫描、停止和继续。
- JPHOO 使用独立的系统 Edge Profile，可复用登录状态。
- 支持 V1 只读迁移、数据备份和安全恢复。
- 页面和命令行均可安全退出 Yav。

## Windows 使用

下载发布页中的：

```text
Yav-V2.exe
SHA256SUMS.txt
```

双击 `Yav-V2.exe` 后，Yav 会：

1. 在 `127.0.0.1` 启动本地服务；
2. 打开默认浏览器；
3. 将业务数据保存到 `%LOCALAPPDATA%\Yav\v2`。

关闭浏览器不会退出 Yav。请使用页面中的 **安全退出 Yav**，或者执行：

```powershell
Yav-V2.exe --shutdown
```

### 常用命令

```powershell
# 指定数据目录
Yav-V2.exe --data-dir "D:\YavData"

# 不自动打开浏览器
Yav-V2.exe --no-browser

# 创建备份
Yav-V2.exe --backup

# 恢复演练
Yav-V2.exe --restore "备份目录" --dry-run

# 正式恢复
Yav-V2.exe --restore "备份目录"

# V1 迁移演练
Yav-V2.exe --migrate-v1 "旧版 library.db" --dry-run

# 正式迁移
Yav-V2.exe --migrate-v1 "旧版 library.db"
```

详细说明：

- [Windows 安装](docs/INSTALL_WINDOWS.md)
- [V1 迁移](docs/MIGRATE_V1_TO_V2.md)
- [备份与恢复](docs/BACKUP_RESTORE.md)
- [发布说明](docs/RELEASE_NOTES_2.0.0.md)

## 开发与测试

```powershell
python -m pip install requests beautifulsoup4 lxml playwright pyinstaller
python -m compileall backend tests yav_v2.py
python -m unittest discover -s tests -v
node --check backend/static/app.js
python -m PyInstaller --noconfirm --clean yav_v2.spec
```

开发模式：

```powershell
python -m backend.app
```

默认地址：`http://127.0.0.1:8765`

## 分支

- `main`：Yav 2.x 正式主分支。
- `v1-frozen`：V1 冻结基线。
- `v2-rebuild`：V2 重建历史分支；2.0.0 发布后不再作为日常主分支。

## 数据边界

不会提交或打包：

- `library.db`
- 浏览器 Profile、Cookie 和登录凭据
- 本地封面
- 日志
- 运行锁和关闭令牌
- 备份目录
