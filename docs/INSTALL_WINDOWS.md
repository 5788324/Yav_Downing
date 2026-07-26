# Windows 安装与启动

发布包只需 `Yav-V2.exe`，不要求安装 Python。将其放到可写目录后双击即可；数据默认保存到 `%LOCALAPPDATA%\Yav\v2`，不在程序目录。

```powershell
.\Yav-V2.exe
.\Yav-V2.exe --data-dir "D:\YavData" --port 8876 --no-browser
```

默认端口为 8765；被占用时自动尝试少量后续本地端口。重复启动会复用已运行实例。日志在 `%LOCALAPPDATA%\Yav\v2\logs\yav.log`，自动轮转，且不会记录磁链、Cookie、Token 或认证头。