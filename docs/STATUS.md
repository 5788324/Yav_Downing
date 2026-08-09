# Yav 当前状态

更新时间：2026-07-30

## 当前结论

**Yav 2.0.2 已完成代码收口、合并和 RC 构建，但尚未正式发布。**

- 仓库：`5788324/Yav_Downing`
- 目标开发分支：`v2-rebuild`
- 修复 PR：#6，已合并
- RC 固定源码 SHA：`fa31539e1bdaf524217f57cfe3524e09e00d16fd`
- 应用版本：`2.0.2`
- 当前阶段：Windows 实机 RC 验收
- 尚未创建 `v2.0.2` 标签、GitHub Release 或正式发布资产

## PR 与 CI

PR #6 的最终 Head：

`a3977252f1335f093b3962a4629d1649d36c953f`

合并提交：

`fa31539e1bdaf524217f57cfe3524e09e00d16fd`

合并前 GitHub Actions run `30526475879` 全绿：

- Ubuntu Python 3.11 / 3.12
- Windows Python 3.11 / 3.12
- Playwright UI 全链路
- Windows PyInstaller 构建、启动和退出

## RC 构建

RC 构建工作流：

- run：`30532474840`
- artifact ID：`8755315523`
- artifact 名称：`Yav-2.0.2-RC-fa31539-windows-x64`
- 固定 checkout：`fa31539e1bdaf524217f57cfe3524e09e00d16fd`
- 构建结果：成功
- 临时构建 PR #7：已关闭，未合并
- 未创建标签或 Release

RC 文件：

- 文件：`Yav-V2-2.0.2-RC.exe`
- 大小：`55,206,988 bytes`
- SHA-256：`918574E5FF886DDBCAA41B542C0EE1B40EA12D1C56AA6B136003880AD9B42BAF`

原 GitHub artifact ZIP：

- SHA-256：`8A301D5AEB0AEF3ABCD1016BC3B25E7A8DD872CEC271BEDE869C4815135BBB28`

## 已完成的隔离验收

在复制的 2.0.1 数据库副本上已经完成：

- schema 3 → 4 首次升级
- 第二次初始化幂等
- `PRAGMA integrity_check = ok`
- 1,498 部影片
- 1,498 个来源页
- 11,747 条磁链
- 11,747 条磁链来源关系
- 1,166 名演员
- 3,308 条影片—演员关系
- 0 非法 BTIH
- 0 Base32 遗留
- 0 片内或跨片规范化重复 BTIH
- 0 无效演员
- 候选 EXE 启动、备份、CLI 安全退出、端口和 runtime 释放通过

## 本轮冻结范围

当前不再开发新功能，也不继续扩展审查范围。

下一步只做 Windows 实机 RC 验收：

1. 校验 RC EXE 哈希。
2. 复制正式 2.0.1 数据目录到全新隔离目录。
3. 检查升级前基线。
4. 使用 RC EXE 完成 schema 升级与二次幂等。
5. 验收首页、筛选、详情、收藏、编辑、来源 CRUD 与 JPHOO 门禁。
6. 验收升级后备份。
7. 验收 UI 和 CLI 安全退出。
8. 验收单实例、端口、runtime、lock 和 Profile 释放。
9. 确认正式数据库和正式 Profile 未被修改。

除非发现数据丢失、数据库损坏、应用无法启动、安全退出失败、资源无法释放或敏感信息泄漏，否则不得重新进入代码开发。

## 发布边界

实机验收结论为 PASS 后，才进入正式发布准备。

正式发布仍需要用户明确授权，届时才能：

- 创建 `v2.0.2` 标签；
- 创建 GitHub Release；
- 上传正式 EXE 和校验文件；
- 决定是否同步到 `main`。

## 交接入口

新对话先阅读：

- `docs/HANDOFF_2026-07-30.md`
- 交接包中的 `prompts/NEW_CHAT_PROMPT.md`
- 交接包中的 `prompts/RC_ACCEPTANCE_CODEX_PROMPT.md`
