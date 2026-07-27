# Yav V2 发布检查清单

更新时间：2026-07-27

## 当前发布目标

RC5 已完成严格替代验收。当前不再增加功能或额外门槛，下一步直接准备正式 `2.0.0`。

## 核心功能

- [x] V2 SQLite 资料库。
- [x] V1 只读迁移、dry-run 和幂等执行。
- [x] 海报墙、收藏架、资料册和组合筛选。
- [x] JavDB 扫描、停止和继续。
- [x] JPHOO 登录恢复、扫描、停止、继续和重启恢复。
- [x] JPHOO 停止后最终状态为 `stopped`。

## 数据保护

- [x] SQLite 快照备份。
- [x] 备份 manifest 和本地封面。
- [x] 恢复 dry-run。
- [x] 恢复前自动备份。
- [x] 恢复失败不覆盖当前数据。
- [x] 浏览器 Profile、Cookie 和 runtime 不进入备份。

## Windows 包和运行控制

- [x] 单文件 `Yav-V2.exe`。
- [x] `--data-dir`、`--port`、`--no-browser`。
- [x] `--backup`、`--restore`、`--migrate-v1`、`--dry-run`。
- [x] 页面安全退出和 `--shutdown`。
- [x] 服务仅监听 `127.0.0.1`。
- [x] 单实例锁在进程生命周期内持续持有。
- [x] 并行启动只有一个实例取得锁。
- [x] 第二实例不会删除现有实例的 runtime。

## 自动测试

以下环境全部通过完整检查：

- [x] Ubuntu + Python 3.11。
- [x] Ubuntu + Python 3.12。
- [x] Windows + Python 3.11。
- [x] Windows + Python 3.12。

每组均通过：

- [x] `python -m compileall backend tests yav_v2.py`。
- [x] `python -m unittest discover -s tests -v`。
- [x] `node --check backend/static/app.js`。
- [x] `git diff --check`。

## RC5 干净 Windows 打包验收

- [x] PyInstaller 构建成功。
- [x] 隔离 PATH 启动，不依赖外部 Python。
- [x] 空数据目录创建数据库。
- [x] 首页、状态 API 和筛选 API 正常。
- [x] 仅监听 `127.0.0.1`。
- [x] 打包版启动系统 Edge。
- [x] 使用独立临时 JPHOO Profile。
- [x] 页面退出返回 HTTP 202。
- [x] 页面退出后进程、端口、Edge 和 runtime 全部释放。
- [x] CLI `--shutdown` 正常。
- [x] 备份正常，manifest 不包含 runtime。
- [x] 恢复 dry-run 不修改当前库。
- [x] 正式恢复通过 SQLite 完整性校验。
- [x] V1 dry-run 不创建 V2 数据库。
- [x] V1 正式迁移和二次幂等迁移通过。
- [x] V1 文件哈希不变。
- [x] 日志中未发现完整磁链、Cookie、Authorization 或关闭令牌。

验收报告：`FINAL_ACCEPTANCE_SUCCESS`。

RC5 验收构建：

- EXE 大小：55,197,900 bytes；
- SHA-256：`823D6DC00835DB368AECF42A693B8711ED93E27DE2D19A6611D35BF50CA0343B`。

## 已豁免的人工步骤

- [x] 用户本人电脑或新建本地 Windows 用户验收：用户当前无法执行，改用干净 Windows 托管 runner 进行严格、可重复的替代验收。

该豁免不表示所有机器环境必然相同。正式使用时若发现硬件、杀毒软件或系统策略特有问题，再按真实问题修复。

## 正式发布

- [ ] 合并 `v2-rebuild` 到 `main`。
- [ ] 从合并后的正式提交重新构建 `Yav-V2.exe`。
- [ ] 记录正式 EXE 大小和 SHA-256。
- [ ] 创建 `v2.0.0` 标签。
- [ ] 发布 EXE、校验值和使用说明。
- [ ] 保留 `v1-frozen`。

## 当前结论

**RC5 验收通过，可以进入正式发布。**
