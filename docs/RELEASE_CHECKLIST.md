# Yav 2.0.0 发布检查清单

更新时间：2026-07-27

## 产品与数据

- [x] SQLite 是唯一业务数据源。
- [x] 海报墙、收藏架和资料册。
- [x] JavDB 扫描、停止和继续。
- [x] JPHOO 登录恢复、扫描、停止、继续和重启恢复。
- [x] V1 只读迁移、dry-run 和幂等执行。
- [x] SQLite 快照备份。
- [x] 恢复校验、dry-run、恢复前自动备份和失败保护。
- [x] Profile、Cookie、runtime 和日志不进入备份。

## Windows 运行

- [x] 单文件 `Yav-V2.exe`。
- [x] 服务仅监听 `127.0.0.1`。
- [x] 页面安全退出。
- [x] CLI `--shutdown`。
- [x] 生命周期单实例锁。
- [x] 并行启动只有一个实例取得锁。
- [x] 退出后进程、端口、Edge 和 runtime 全部释放。

## 自动测试

- [x] Ubuntu + Python 3.11。
- [x] Ubuntu + Python 3.12。
- [x] Windows + Python 3.11。
- [x] Windows + Python 3.12。
- [x] Python 编译检查。
- [x] 完整单元测试。
- [x] JavaScript 语法检查。
- [x] Git 空白检查。

## 干净 Windows 打包验收

- [x] 隔离 PATH 启动，不依赖外部 Python。
- [x] 空资料库创建数据库。
- [x] 首页、状态 API 和筛选 API。
- [x] 打包版启动系统 Edge。
- [x] 独立临时 JPHOO Profile。
- [x] 页面和 CLI 安全退出。
- [x] 备份与恢复。
- [x] V1 dry-run、正式迁移和二次幂等迁移。
- [x] SQLite `integrity_check`。
- [x] 日志敏感信息检查。

验收报告：`FINAL_ACCEPTANCE_SUCCESS`

## 正式发布

- [x] 版本号切换为 `2.0.0`。
- [ ] 合并 `v2-rebuild` 到 `main`。
- [ ] 从正式合并提交重新测试并构建 Windows EXE。
- [ ] 生成 `SHA256SUMS.txt`。
- [ ] 创建 `v2.0.0` 标签。
- [ ] 创建 GitHub Release 并上传 EXE、校验值和发布说明。
- [x] 保留 `v1-frozen`。

## 结论

Yav 2.0.0 已满足发布条件。剩余未勾选项目由正式发布工作流完成。
