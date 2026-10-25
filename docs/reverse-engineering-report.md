# ReadCube Papers API 逆向研究报告

研究日期：2026-10-24 至 2026-10-25。操作范围为用户本人会话；写入仅在单独授权的 `Codex API Test 2026-10-24` 私有 Collection。正式库文献未修改。未使用验证码、MFA、访问控制或限流绕过。

## 结论

三个关键问题已用真实请求验证：通过顶层 ext_ids 新增 DOI/PMID；通过 add_file → 签名地址 PUT → uploads_pending → add_file 关联 PDF；通过专用笔记/标签/List 接口管理用户数据。

当前 SDK 目录 **38 项能力均有真实请求及语义检查证据**。新增便签/单页高亮、批注修改/删除、PDF 新建记录、补充 PDF/主文件切换、Smart List CRUD、metadata 与 revisions 读取、Bayeux 事件监听均已验证。证据仅覆盖文档所列输入和当前账户，不表示所有角色、文件类型或认证分支均已支持。实时监听采用通知加完整扫描补偿，没有持久增量游标。

## 阶段一：公开资料与实现源码

| 材料 | 固定版本/日期 | 实际审阅内容 | 证据能力 |
|---|---|---|---|
| [API 博客](https://blog.hxgpark.com/posts/ReadCubePapersAPI/) | 2022-05-21 | form 登录、GET、notes PATCH、Bayeux 描述 | 历史 SOURCE_CONFIRMED；不是当前成功证明 |
| [Python 项目](https://github.com/YusukeKimata-Moo/readcube-papers-skill/tree/38e35f4089f720560724537be764685294098e73) | commit `38e35f4089f720560724537be764685294098e73` | `scripts/readcube_papers.py` 的 login/get_items/get_item/get_annotations/search/_parse_item | 明确使用的读取路径；没有 DOI/PDF 写入实现 |
| [Overleaf Gist](https://gist.github.com/MichalPt/0d08085321d03a63aca07720785849c8/aa97173f59786b759c73cd71ced261c3fe97e011) | revision `aa97173f59786b759c73cd71ced261c3fe97e011`，说明 Papers 5.0.13 | `readleaf.user.js` 的 fetchItems、List URL 构造、scroll_id、article/ext_ids/user_data 转 BibTeX | 确认 List items 与分页/字段使用 |

直接查看了代码，不以 README 代替实现。博客指向的旧 Joplin 两个 TS 文件当前 404，因此未把失效链接视为可复核源码；未执行下载的第三方脚本。

公开检索还找到了 ReadCube 官方 [发布说明](https://about.readcube.com/release-notes/) 和 [元数据处理说明](https://about.readcube.com/help-center/metadata-resolving-incomplete-records/)。它们可说明产品行为，但不证明某个私有 HTTP 请求格式。API 级结论优先依据当前公开 bundle 和本人的真实请求。

阶段产物：`research/phase-1-2.json`、下载的固定版本第三方源文件（`research/sources/`，Git 忽略），以及最终接口目录。

## 阶段二：当前 Web 前端

给定旧入口 `https://www.readcube.com/papers/` 的直接 HTTP 获取返回 403，未绕过。当前 `https://app.readcube.com/` 的公开 HTML 和 JS 正常可取；浏览器打开后也显示已有用户会话。源码读取与 API 会话验证分开进行。

从 HTML 实际引用的 `main-UTNWQQUS.js` 开始，只递归获取 bundle 中明确引用的 `chunk-*.js`，共 47 个 entry/chunk 资产；未枚举猜测 REST 路径。未发现 sourceMappingURL footer，未声称存在公开 source map。

主要源码锚点：

| 资产 | SHA-256 / 用途 |
|---|---|
| `main-UTNWQQUS.js` | `be26f036c79dcd79c298054f5b2b66c12d5ed952dc829c4cbf51f24d3d5a121f`；HTTP interceptor、公共参数、withCredentials |
| `chunk-QD3Q3KF7.js` | 版本常量 5.4.24、baseUrls、Collection/Item/List API、上传器 PUT、Bayeux、分页 |
| `chunk-JCLW3CJS.js` | identifier import、文件 SHA-256、add_file/upload_file 初始化、poll/reassociate、Collection 创建表单 |

后两者完整 hash 与所有资产 URL 见 `research/public-assets.json`，避免手工转抄。逐项接口 source URL 与字符偏移在 `readcube_client/endpoints.json`；偏移适用于对应已固定 hash 的原始 JS，不是行号。执行 `scripts/build_catalog.py` 会核对 reviewed needle 的存在；前端变化时应重新审阅再更新，不能直接自动提升证据等级。

源文件只作研究缓存，未把完整 ReadCube 前端源码打包进 wheel。摘录缓存同样位于被 Git 忽略的 research/sources，避免发布无关 telemetry 配置。未解析或导出浏览器的隐藏会话。

## 阶段三：初轮实测与证据（2026-10-24）

浏览器工具可见已有登录，但不提供 Network/HAR/会话导出。用户选择在本机终端运行安全登录助手；工具限制禁止代理操作终端 UI，因此用户手动输入邮箱/密码。会话 Cookie 留在 `~/.config/readcube-client/session.json`，没有写入项目源码、公开报告或工具日志。

随后实际通过 API 读取到本人账户 Collection；经用户授权创建私有测试库。写入前将预期操作保存为 dry-run 计划，不向其他成员发送邀请。测试生成的 PDF 只含一行合成文本，不含个人或论文全文。

| 验证内容 | 结果与检查 |
|---|---|
| Collections / Lists / items / get_item | HTTP 200；校验对象 IDs 和 envelope |
| 强制 size=1 分页 | 2 条有效记录、3 次 GET；含末尾空页，无重复 ID |
| DOI 导入 | 独立 GET 读到目标 DOI；再次查重返回已有项 |
| PMID 导入 | 实际 POST 后独立 GET 读到 PMID，并合并回相同测试资源 |
| 手动元数据创建 / PATCH 更新 | 合成标题创建成功，再次 GET 确认更新 |
| notes / set_tags / add_tags / remove_tags | 每次写后 GET 与预期文本/标签集一致 |
| List 创建、重命名、成员加入/移出 | 独立 Lists/items GET 确认；处理索引传播延迟 |
| PDF 关联 | S3 PUT 200、pending 完成、再次关联、GET 中 hash 一致 |
| 单条文献与 List 删除 | 用户额外确认精确对象后执行；独立读取确认 tombstone/缺失 |
| annotations GET | 成功返回数组；测试库内为空，没有推断坐标/颜色完整语义 |
| 本地差异同步 | 两次完整扫描一致；没有误报新增/修改/缺失 |
| MCP stdio | 标准客户端 initialize → list_tools → capabilities → 真实账户查询成功 |

PDF 测试 hash：`059f5749255d5252765a0995216216968e733f6a013fb2bbc0b21f3f31abb690`。签名上传 URL 不记录；只保留实际 host `s3.amazonaws.com`。对初次遇到的非白名单 host，客户端中止；确认它是本人请求从已认证 ReadCube 返回的 S3 地址后，才在本地测试配置加入该准确 host 并重测。

第一次端到端测试在即时 List 成员读回时失败，首次即时 DOI 去重也未命中；报告保留了这些失败，没有改写成成功。后续实测和当前源码中的刷新延时均支持“搜索索引最终一致”的解释。修正为：写操作不重复发送；验证脚本有上限地轮询只读结果；同一 SDK 实例记住新导入 ID 并 GET 确认；服务器新增继续 merge=true。修正后成员和重复文献检查通过。

删除仅涉及用户单独批准的合成测试文献及一个 List。库、DOI 测试文献、早期验证遗留的合成记录和 List 保留，便于审计。没有用删除正式文献来验证接口。

脱敏结果在 `docs/verification-results.json`；原始执行检查、仅本机资源 ID、删除预览等在 `research/private/`，运行时门控在用户配置目录。公开结果包含状态、检查时间、契约 hash 和检查说明，不包含 Cookie、会话 fingerprint、用户库内容或签名 URL。

## 版本冲突与还原选择

| 差异 | 处理 |
|---|---|
| 博客 `scoll_id` 与实现 `scroll_id` | 采用源码与真实分页一致的 scroll_id |
| 历史 sync/collections/ 与当前 services/collections | 正式 SDK 采用当前前端 services 路径；历史入口返回 301，并指向 services/collections |
| 历史笔记 PATCH 与当前 set_notes | 正式笔记方法使用已实测 set_notes；不假定旧写法仍等价 |
| Python 扁平化字段与原始嵌套字段 | SDK 保留 article/ext_ids/user_data 及未知字段，避免信息丢失 |
| DOI 手动 item envelope 与 identifier add | 分成 create_item 与 import_by_doi/pmid 两类已验证请求契约 |
| 直接 multipart 上传的直觉 | 不采用；实际为 hash 初始化、PUT、poll、再次关联 |
| 历史 clientId 依赖 | 已测 HTTP 用空 client_id 成功；不据此推断 WebSocket 无需握手 |

## 阶段四至六：SDK、测试和 MCP

SDK 使用 httpx、pydantic、pydantic-settings，支持配置、JSON CLI、作用域 Cookie、超时、仅 GET 重试、dry-run、写入白名单和单独删除确认。正式模块与显式研究模块分离；MCP 只导入正式模块。客户端记录的成功必须再由研究脚本的语义检查提升，单元 Mock 不会生成真实 VERIFIED 记录。

初轮 48 项本地测试覆盖认证边界、配置、精确 DOI、索引延迟去重、相同 cursor 推进、重复页/丢失 cursor、快照不被失败扫描覆盖、重试策略、非 JSON/业务错误、Cookie 域与文件权限、文件根目录、未验证门控和 MCP schema/错误通道。2 项真实只读集成测试与独立强制分页测试通过；MCP 真正启动为子进程并经 stdio 初始化，不只测试 Python 函数导入。

初轮 MCP 提供 16 个工具、结构化 JSON、readOnly/destructive 注解和显式写参数，删除有独立确认文本。已生成可运行的本机 stdio 配置，未修改其他 Agent 的全局设置。

## 2026-10-25 补充验证

| 原未解决项 | 本轮完成情况 | 证据/边界 |
|---|---|---|
| 认证状态 | 过期 Cookie 过滤、安全原子保存、独立空 jar 登录、保存前 GET 验证、错误分类；现有会话只读检查通过 | 当前公开 password form 已确认；新版完整登录仍需用户正常输入凭据实测，不声称 SSO/MFA |
| 批注 | 合成 PDF 上新增便签和单页高亮、精确读回字段；便签文字/颜色修改；经精确授权删除便签，保留高亮 | POST bulk_single，外层 item ID / 内层 annotation ID；当前 viewer-core 13.7.0 确认坐标与颜色 |
| 实时同步 | JSONP 握手、WSS 订阅、心跳；受控笔记修改对应 item updated 事件；断线期间修改由新连接完整扫描恢复 | 无可重放游标；事件只是扫描触发信号，`watch_changes` 返回 notification_assisted_full_scan |
| PDF 变体 | 新 hash 的直接 PDF 上传创建记录；第二 PDF 成为 supplement；set_primary 后 GET 核对 hash | files 内部字段实际为 sha256，已修复旧 hash 检查遗漏 |
| Smart List | 新建、读取、修改 name/query、经精确授权删除并确认 GET 404 和列表缺失 | 查询保存验证通过，不声称穷举搜索语法或共享权限 |
| 历史辅助读取 | reader_metadata 正式封装并核对 DOI；get_revisions 返回数组 | 本次 revisions 为空，不推断历史版本恢复或增量游标 |

新增源码细节分别在 `research/annotation-findings.md`、`research/realtime-findings.md`、`research/auth-findings.md`。当前 viewer-core 与认证页面只下载其明确引用的公开文件，没有执行第三方脚本或导出隐藏会话。

**保留的失败与修正：** 上传补充 PDF 后初次读回检查误判失败，服务端实际已保存；原因是附件列表使用 sha256 字段，而旧检查只读取 hash。修正后同一附件与主文件切换均确认。随后同 hash PDF 的服务器 merge=true 仍产生了两条匹配记录，证明不能依靠此参数保证去重；SDK 新增完整扫描 SHA-256 查重，以及按会话/库隔离的本地 recent-ID 缓存并 GET 核验。实测修复后返回 needs_review=true、2 个候选、零写请求。测试重复对象保留，未擅自批量清理。并发导入仍非事务性唯一约束。

Smart List 删除后的 GET 实际返回 404，而首版验证脚本只预期 tombstone，导致脚本在成功删除后退出。随后独立 GET 404 和列表缺失确认删除；未重复 DELETE。该次 DELETE 的精确状态码未持久化，证据快照保留 http_status=null，并明确记录“已通过客户端 2xx/JSON 成功检查”，不补造 200。脚本现支持 tombstone/404，并在写后立即保存审计。

最终回归：149 项本地测试通过，2 项真实只读集成测试通过；ruff 与 27 工具 stdio MCP 检查通过。Mock 不会写入真实验证 ledger。

新版 MCP **27 个工具**，版本 0.2.0；新增批注、PDF 导入、Smart List、辅助读取及有时长上限的监听。所有写入仍默认 dry-run，删除仍要求单独精确确认。新增验证脚本默认不写入，`--execute` 才执行已授权范围。

## 尚未解决的问题（收窄后的边界）

1. **认证特殊分支**：当前账户会话可用，密码 form 已确认；SSO、MFA、CAPTCHA、强制 authenticity_token/CSRF 分支及完整新版密码登录尚未逐一实测。没有发现可据以实现的独立 refresh-token 契约；失效会话须正常重新登录。SDK login 继续明确报 UNVERIFIED，安全助手可以本机交互重登录。
2. **持久服务端增量**：已完成真实事件与断线补偿验证，但仍没有持久 delta cursor/replay 协议。重连、周期和结束均全扫描；服务端搜索索引的可见性延迟不能被瞬间消除。
3. **PDF/批注特殊情况**：非 PDF 附件、订阅/尺寸上限、旋转/crop/user-unit 页面及跨页高亮未验证。单页几何字段已精确读回；本轮没有浏览器视觉覆盖确认。多条同 hash 项交由人工判断，不自动合并/删除。
4. **复杂权限与并发**：缺少专用共享/只读/组织受限测试身份，未改变成员角色或邀请他人。深层 List 上限、条件写/并发冲突仍未建立可验证契约。现有本人私有测试库的普通 List 与 Smart List CRUD 已完成。
5. **服务端异常全集**：客户端有有界重试和错误协议测试；未故意耗尽限额、制造 5xx 或试探他人资源。无法宣称穷举真实限流/错误码。

后续需要的外部条件明确：用户正常走特殊认证流程并提供合法脱敏请求证据、另行授权的权限矩阵测试账户、或特定附件/页面样本。现有安全且已授权的测试范围已继续完成；正式文献未修改。
