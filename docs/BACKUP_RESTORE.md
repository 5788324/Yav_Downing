# 备份与恢复

```powershell
.\Yav-V2.exe --backup
.\Yav-V2.exe --restore "D:\YavData\backups\yav-v2-backup-..." --dry-run
.\Yav-V2.exe --restore "D:\YavData\backups\yav-v2-backup-..."
```

备份目录含 `library.db`、存在的本地封面、`manifest.json`（格式版本、创建时间、文件大小清单）；不含 Cookie、浏览器 profile 或密钥。恢复先校验清单及文件大小；dry-run 不写入。正式恢复拒绝正在运行/占用的库，先自动备份当前 V2，然后复制到临时区并在完整后替换数据库。任何校验或复制失败都会保留当前库。浏览器登录资料不会被恢复或覆盖。