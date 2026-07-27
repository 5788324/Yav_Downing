# Yav V2 当前状态

更新时间：2026-07-27

## 一句话结论

Yav V2 RC5 已完成代码、跨平台自动测试和干净 Windows 打包验收。当前没有已知发布阻塞缺陷，下一步只剩正式发布。

## 当前基线

- 分支：`v2-rebuild`
- 代码版本：`2.0.0-rc5`
- 验收构建环境：GitHub 托管 Windows Server 2025，Python 3.12
- RC5 EXE 大小：55,197,900 bytes
- RC5 SHA-256：`823D6DC00835DB368AECF42A693B8711ED93E27DE2D19A6611D35BF50CA0343B`

该构建来自干净 Windows runner，不依赖用户电脑中的 Python、源码或虚拟环境。它不是用户本人电脑上的人工点击测试，但已作为本轮无法执行实机验收时的严格替代验收。

## 已完成

### 核心产品

- SQLite 是唯一业务数据源。
- 支持影片、演员、来源页面、磁链、收藏和手工资料。
- 磁链按 BTIH 去重，同一磁链可保留多个来源。
- 支持海报墙、收藏架、资料册、搜索、组合筛选、详情和编辑。
- V1 可只读迁移到 V2，支持 dry-run 和重复执行。

### 来源扫描

- JavDB：全量扫描、继续、停止、进度和磁链写入。
- JPHOO：统一 Edge Profile、登录恢复、扫描、停止、继续和重启恢复。
- 扫描中退出会先停止扫描，再释放浏览器和 Profile。
- JPHOO 停止后最终状态为 `stopped`，不会误报 `failed`。

### 数据保护和运行控制

- SQLite 快照、本地封面和 manifest 备份。
- 恢复校验、dry-run、恢复前自动备份和失败保护。
- 页面安全退出和 `Yav-V2.exe --shutdown`。
- 服务只监听 `127.0.0.1`。
- 单实例锁在整个进程生命周期内持续持有。
- 两个并行进程竞争时只有一个能取得实例锁。

## 严格验收结果

### 干净测试环境

以下四组完整检查全部通过：

- Ubuntu，Python 3.11；
- Ubuntu，Python 3.12；
- Windows，Python 3.11；
- Windows，Python 3.12。

每组均执行：

- `python -m compileall backend tests yav_v2.py`；
- `python -m unittest discover -s tests -v`；
- `node --check backend/static/app.js`；
- `git diff --check`。

### Windows 打包端到端

在干净 Windows runner 中实际完成：

- PyInstaller 单文件 EXE 构建；
- 隔离 PATH 启动，不依赖外部 Python；
- 空数据目录创建 `library.db`；
- 首页、状态和筛选 API；
- 仅监听 `127.0.0.1`；
- 打包版 Playwright 启动系统 Edge；
- 使用独立临时 JPHOO Profile；
- 页面 API 安全退出，HTTP 202；
- CLI `--shutdown`；
- 退出后进程、端口、Edge 和 runtime 文件全部释放；
- 备份、恢复 dry-run 和正式恢复；
- V1 dry-run、正式迁移和二次幂等迁移；
- V1 文件哈希保持不变；
- SQLite `integrity_check`；
- 日志未发现完整磁链、Cookie、授权信息或关闭令牌。

最终验收报告状态：`FINAL_ACCEPTANCE_SUCCESS`。

## 尚未执行但不再阻塞

- 用户本人电脑或新建本地 Windows 用户中的人工点击验收。

原因：用户当前无法执行。已经用干净 Windows 托管环境完成更可重复的替代验收。若正式使用时发现机器特定问题，再按实际缺陷处理，不继续预设新门槛。

## 发布路线

```text
RC5 严格验收通过
→ 合并 v2-rebuild 到 main
→ 从合并提交重新构建正式 2.0.0
→ 计算正式 SHA-256
→ 创建 v2.0.0 标签
→ 发布 EXE 和使用说明
```

## 发布判断

当前判断：**RC5 验收通过，可以进入正式发布。**
