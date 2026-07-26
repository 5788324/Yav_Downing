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
## RC2 安全退出

关闭浏览器不会退出 Yav。请使用页面中的“安全退出 Yav”或 `Yav-V2.exe --shutdown`；两者都会停止扫描并释放本地端口、锁和临时运行凭据。RC1 因缺少正常退出入口未完成单实例验收；RC2 已完成打包版 CLI 退出验证。JPHOO 打包版真实登录与扫描仍是发布阻塞项。

## RC2 打包版 JPHOO 临时验收

使用先前独立临时 profile 的新副本完成：首次打开为 `ready`，应用正常退出并重启后仍为 `ready`；小范围继续扫描进入 `running`，停止请求进入 `stopping`，随后使用安全退出关闭应用。进程、端口和锁均释放，临时 profile 仍存在。未修改正式 V2 数据或 profile。

## RC3 补充验收

- [x] 独立空库启动后，页面正常显示迁移引导和“安全退出 Yav”入口。
- [x] 同一 RC3 实例的 `--shutdown` 实测释放端口、实例锁和临时运行凭据。
- [x] `python -m compileall backend tests yav_v2.py`、39 项单元测试、`node --check backend/static/app.js` 与 `git diff --check` 通过。
- [x] 临时验收数据库和运行目录已删除；没有修改正式 V1/V2 数据、浏览器 profile 或 V1 磁链。
## RC4 本机隔离验收（2026-07-27）

- [x] RC4 使用独立 `runtime\instance.json` 与 `runtime\shutdown.secret`，均使用临时文件原子替换；实例文件不含 token。
- [x] 源码模式：状态身份正确、第二实例拒绝、CLI `--shutdown` 返回 `stopped`，监听端口、进程和 runtime 目录均释放。
- [x] 打包 RC4：仓库外副本启动，首页、`/api/filters`、`/api/app/status` 均可用；页面实际 bootstrap/Origin/POST 协议获得 202 后服务断开并清理 runtime；打包 CLI 再次验证退出。
- [x] 打包备份、dry-run 恢复、正式恢复与合成 V1 迁移均在临时数据目录通过；备份 manifest 不含 runtime，V1 哈希未变且二次迁移幂等。
- [x] 自动验证 46 项通过。
- [x] RC4 已登录 JPHOO 打包版真实扫描复验：复制临时 profile 后连续重启均为 ready；扫描进入 running，停止进入 stopping 后收敛为 stopped；页面和 CLI 的扫描中退出均释放 Edge、端口、锁与 runtime。
- [ ] Windows Sandbox/全新用户环境验收仍未完成。

发布产物：`release\Yav-V2-2.0.0-rc4\Yav-V2.exe`，SHA-256 为 `4580E84B5611D91BD3A50B0D9329B2A458A73878C6BB2F730C143B11827111A1`；发布产物不提交 Git。