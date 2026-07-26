# Windows 安装与启动

发布包只需 `Yav-V2.exe`，不要求安装 Python。将其放到可写目录后双击即可；数据默认保存到 `%LOCALAPPDATA%\Yav\v2`，不在程序目录。

```powershell
.\Yav-V2.exe
.\Yav-V2.exe --data-dir "D:\YavData" --port 8876 --no-browser
```

默认端口为 8765；被占用时自动尝试少量后续本地端口。重复启动会复用已运行实例。日志在 `%LOCALAPPDATA%\Yav\v2\logs\yav.log`，自动轮转，且不会记录磁链、Cookie、Token 或认证头。
## RC2 安全退出

关闭浏览器不会退出 Yav。请使用页面中的“安全退出 Yav”或 `Yav-V2.exe --shutdown`；两者都会停止扫描并释放本地端口、锁和临时运行凭据。RC1 因缺少正常退出入口未完成单实例验收；RC2 已完成打包版 CLI 退出验证。JPHOO 打包版真实登录与扫描仍是发布阻塞项。

## RC4 安全退出

页面“安全退出 Yav”会先停止扫描，再关闭本地服务。命令行 `Yav-V2.exe --shutdown` 会读取同一数据目录的临时运行文件，校验 PID、端口、实例 ID 和 `/api/app/status` 的 Yav 身份后才发送关闭请求，并等待端口释放。关闭浏览器不会退出程序。