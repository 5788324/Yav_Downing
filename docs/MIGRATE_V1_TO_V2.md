# 从 V1 迁移到 V2

先退出 V1。迁移始终以只读方式打开旧库，绝不复制或改动旧库、V1 配置或浏览器资料。

```powershell
# 默认演练：不创建或修改 V2 library.db
.\Yav-V2.exe --data-dir "D:\YavV2" --migrate-v1 "D:\YavV1\library.db" --dry-run
# 确认演练统计后才实际导入
.\Yav-V2.exe --data-dir "D:\YavV2" --migrate-v1 "D:\YavV1\library.db"
```

演练/完成报告包含影片、来源页、磁链、磁链来源关联、演员及关联数和冲突数；重复执行按来源页和影片 BTIH 去重。若目标 V2 已有资料，正式导入前自动备份。导入后检查日志与图书馆数量；失败会明确标示读取 V1 或写入 V2 阶段。