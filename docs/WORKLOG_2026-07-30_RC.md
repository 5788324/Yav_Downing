# Yav 2.0.2 RC 工作日志续篇

日期：2026-07-30

## PR #6 合并

- 修复分支：`codex/fix-library-scan-refresh`
- 最终 Head：`a3977252f1335f093b3962a4629d1649d36c953f`
- 合并目标：`v2-rebuild`
- 合并方式：merge commit
- 合并 SHA：`fa31539e1bdaf524217f57cfe3524e09e00d16fd`
- PR #6 已关闭并合并。
- 未合并到 `main`，未创建标签或 Release。

合并前 run `30526475879` 的四组 Python、Playwright UI 和 Windows PyInstaller 全部成功。

## RC 构建

为避免把临时构建工作流合并进 `v2-rebuild`，创建了临时分支 `rc/2.0.2-build` 和 Draft PR #7。

RC 工作流固定 checkout 合并 SHA：

`fa31539e1bdaf524217f57cfe3524e09e00d16fd`

工作流 run `30532474840` 成功完成：

- 固定源码 SHA 校验；
- Python 单元测试；
- JavaScript 和 Node 扫描状态检查；
- PyInstaller 构建；
- EXE 启动与 API 版本 `2.0.2` 校验；
- CLI 安全退出和端口释放；
- RC manifest 与 SHA-256 生成；
- artifact 上传。

产物：

- `Yav-V2-2.0.2-RC.exe`
- 55,206,988 bytes
- SHA-256 `918574E5FF886DDBCAA41B542C0EE1B40EA12D1C56AA6B136003880AD9B42BAF`
- artifact ID `8755315523`
- artifact 名称 `Yav-2.0.2-RC-fa31539-windows-x64`

临时 PR #7 随后关闭且未合并。RC 构建没有创建正式标签、Release 或发布资产。

## 当前唯一任务

由 Codex 在 Windows 实机上执行隔离 RC 验收：

- 正式数据只允许复制，不允许直接启动或写入；
- 验收 schema 3→4、二次幂等和数据库完整性；
- 验收真实 UI、备份、安全退出、单实例和 Profile 释放；
- 发现问题只保存证据，不自行修复代码；
- 完成后输出 PASS / FAIL / PASS WITH NOTES 报告。

## 范围控制

不再处理以下后续架构项：

- 目录编号或来源影片 ID 身份模型；
- 多来源字段自动重聚合；
- 演员来源关系表；
- HTTP 请求瞬时取消；
- `new_movies` 精确统计重构；
- UI 重构、性能优化或新数据源。

## 仓库备注

在 PR #6 标记 Ready 的操作过程中，`main` 历史中曾产生一个空文件提交，随后立即由第二个提交删除。最终文件树已恢复，没有修改应用代码或发布资产。不要为清理这两个互相抵消的历史提交而强制改写 `main`。
