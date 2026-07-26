# 2.0.0-rc1 发布检查

- [x] V1 dry-run 使用只读连接，正式迁移可重复执行。
- [x] 备份清单、恢复 dry-run、预恢复备份与失败保护有自动测试。
- [x] 统一 EXE 参数、日志脱敏、陈旧锁清理有自动测试。
- [x] `python -m compileall backend tests`
- [x] `python -m unittest discover -s tests -v`
- [x] `node --check backend/static/app.js`
- [x] `git diff --check`
- [ ] 在 Windows Sandbox 或全新用户环境完成最终人工验收。
- [ ] 用发布包完成一次手动 JPHOO 登录与小范围扫描。

发布产物：`release\Yav-V2-2.0.0-rc1\Yav-V2.exe`、`README.txt`、`SHA256SUMS.txt`。发布产物、数据库、profile、日志和备份均不提交。