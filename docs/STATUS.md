# Yav 当前状态

更新时间：2026-08-13

## 当前结论

**Yav 2.0.2 已正式发布；当前正在发布后的独立修复分支进行真实数据与易用性改进。**

- 仓库：`5788324/Yav_Downing`
- 正式发布基线：`main @ 42a163be034161e31bc6daf7bd6a191dda7054ee`
- 正式标签：`v2.0.2`
- 当前工作分支：`codex/fix-javdb-direct-cover-image`
- 当前本地提交：`bd466c35850b95a6923174ba1f0c28b3a1c04fb3`
- 当前阶段：真实系列数据补全与 UI 易用性修复；尚未推送或发布新版本
## 2026-08-13：真实数据 UI 易用性审查

- 使用当前 5,282 部影片、47,373 条磁链的真实资料库逐项检查海报墙、收藏架、资料册、组合筛选、分页、收藏、详情磁链、编辑、来源管理和 900px 窄窗。
- 修复首屏信息区过高、搜索必须按 Enter、数千演员原生下拉难以使用、编辑没有取消、来源表单标签不清、关闭按钮随长页面滚走、危险按钮辨识弱和局部文字对比度不足。
- 发现 JavDB 厂商选择器会命中顶部“片商”导航；已改为只读取详情面板字段，并清理自动写入的脏值。真实库修改前已创建 SQLite 备份；清理后影片和磁链数量不变，完整性检查为 `ok`。1 条受 `manual_fields.studio` 保护的旧值按规则保留。
- 验证：Python 72 项、Node 2 项、Playwright 全链路 1 项通过；900px 下无横向滚动。截图、测试数据库、日志和 Node 临时依赖未纳入 Git。
## 2.0.2 RC 历史记录

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

## 2026-08-12：Vixen 系列补采

- 已配置并全量重扫 JavDB Vixen 系列 `https://javdb.com/series/K6eO`。
- 已入库 634 部影片；封面、演员、日期、厂商和时长覆盖均为 634，磁链来源关联 6,647 条，数据库完整性检查为 `ok`。
- 修复 JavDB 当前 `img.video-cover` 直连封面解析；普通 HTTP 无法读取的 3 个版权地区限制页面未写入猜测资料，保留既有失败记录以便后续重试。

## 2026-08-13：七个 JavDB 系列全量更新

- 对用户提供的 8 个链接去重后，新增并全量扫描 Tushy、Blackedraw、Blacked、Wifey、Deeper、Milfy、Tushyraw 共 7 个系列。
- 合计入库 3,131 个来源页，封面、演员、日期、厂商和时长均完整；新增磁链来源关联 28,894 条。
- 扫描后全库共 5,282 部影片、47,373 条磁链；来源 URL 和影片内 BTIH 均无重复，`PRAGMA integrity_check = ok`。

## 2026-08-16：JPHOO 单片真实试跑

- 使用应用隔离 Profile 成功登录 JPHOO，并配置系列 `https://www.jphoo.net/series/9785513050636357`（来源配置 ID 10）。
- 为保证范围确定，只处理第一页首个作品 URL `https://www.jphoo.net/works/13401596825310214`，没有启动全系列扫描。
- 新增 1 部影片、1 个来源页和 12 条唯一 BTIH；封面、系列和 4 位演员入库成功。该页面未提供日期，时长显示为 0 分钟，因此按未知保留。
- 修复 JPHOO 元数据解析：只从 `.q-item__label` 资料块读取厂商/系列，兼容 `/performer/` 演员链接，并拒绝将 0 分钟写成有效时长；避免导航“厂商大全/番号分类”污染资料。
- 试跑后全库为 5,283 部影片、5,283 个来源页、47,385 条磁链，`PRAGMA integrity_check=ok`。JPHOO 专项测试 10 项通过；尚未开始批量扫描。