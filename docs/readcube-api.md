# ReadCube Papers Web API

本轮发现/验证日期：2026-10-24 至 2026-10-25；当前公开前端版本 **5.4.24**。以下均为非官方接口契约。

## 证据与运行状态

- `VERIFIED`：本轮真实请求成功，并完成对应语义检查；写入一般有独立 GET 确认。
- `SOURCE_CONFIRMED`：公开源码明确使用，但不能据此认为当前账户调用成功。
- `INFERRED`：有依据的推断；本项目不将其作为可执行路径。
- `UNKNOWN`：尚无完整请求契约。
- `UNVERIFIED` 是验证状态，可与 `SOURCE_CONFIRMED` 同时出现。

证据层级和当前运行状态分开存储。正式 SDK 还要求本机、当前会话的 verification ledger 与接口契约 SHA-256 一致。`docs/verification-results.json` 为可分享的脱敏实测快照，不能用于绕过运行时门控。

## 地址与共同要求

| Host 名称 | Origin |
|---|---|
| services | `https://services.readcube.com` |
| sync | `https://sync.readcube.com` |
| push | `https://push.readcube.com/bayeux` / `wss://push.readcube.com/bayeux` |

当前前端的 HTTP interceptor 为上述业务请求附加 `Accept: application/json`、`client=webapp`、`client_id`、`client_version=5.4.24`，并启用跨域 Cookie。SDK 当前使用 `client_id=""`；本轮已验证的 HTTP 操作不依赖已连接的 WebSocket clientId。

会话来自合法登录得到的 Cookie，按 domain/path/secure/expiry 保存和发送。历史名称包括 `_readcube-login_token`、`_readcube_session`、`user_web_token`，**不要硬编码必须正好有这三个**。不保存用户密码；Cookie 明文仅保存在本机 `0600` 文件中。HTTP 重定向不自动跟随，避免会话误发。

## 接口目录

下面表格由 `readcube_client/endpoints.json` 与本轮实测 ledger 生成，完整表也在 [api-table.md](api-table.md)。`FLOW` 表示组合工作流，不是新的 HTTP 路径。

| 操作 | 方法 | Host | 路径 | 本轮状态 |
|---|---|---|---|---|
| `list_collections` | GET | `services` | `/collections` | VERIFIED / SOURCE_CONFIRMED |
| `list_lists` | GET | `sync` | `/collections/{collection_id}/lists` | VERIFIED / SOURCE_CONFIRMED |
| `list_items` | GET | `sync` | `/collections/{collection_id}/items` | VERIFIED / SOURCE_CONFIRMED |
| `list_list_items` | GET | `sync` | `/collections/{collection_id}/lists/{list_id}/items` | VERIFIED / SOURCE_CONFIRMED |
| `get_item` | GET | `sync` | `/collections/{collection_id}/items/{item_id}` | VERIFIED / SOURCE_CONFIRMED |
| `create_collection` | POST | `services` | `/collections` | VERIFIED / SOURCE_CONFIRMED |
| `create_item` | POST | `sync` | `/collections/{collection_id}/items` | VERIFIED / SOURCE_CONFIRMED |
| `import_identifier` | POST | `sync` | `/collections/{collection_id}/items` | VERIFIED / SOURCE_CONFIRMED |
| `update_metadata` | PATCH | `sync` | `/collections/{collection_id}/items/{item_id}` | VERIFIED / SOURCE_CONFIRMED |
| `update_notes` | POST | `sync` | `/collections/{collection_id}/items/{item_id}/set_notes` | VERIFIED / SOURCE_CONFIRMED |
| `set_tags` | POST | `sync` | `/collections/{collection_id}/items/{item_id}/set_tags` | VERIFIED / SOURCE_CONFIRMED |
| `add_tags` | POST | `sync` | `/collections/{collection_id}/items/{item_id}/add_tags` | VERIFIED / SOURCE_CONFIRMED |
| `remove_tags` | POST | `sync` | `/collections/{collection_id}/items/{item_id}/remove_tags` | VERIFIED / SOURCE_CONFIRMED |
| `delete_item` | DELETE | `sync` | `/collections/{collection_id}/items/{item_id}` | VERIFIED / SOURCE_CONFIRMED |
| `get_annotations` | GET | `sync` | `/collections/{collection_id}/items/{item_id}/annotations` | VERIFIED / SOURCE_CONFIRMED |
| `update_annotation` | PATCH | `sync` | `/collections/{collection_id}/items/{item_id}/annotations/{annotation_id}` | VERIFIED / SOURCE_CONFIRMED |
| `delete_annotation` | DELETE | `sync` | `/collections/{collection_id}/items/{item_id}/annotations/{annotation_id}` | VERIFIED / SOURCE_CONFIRMED |
| `create_list` | POST | `sync` | `/collections/{collection_id}/lists` | VERIFIED / SOURCE_CONFIRMED |
| `rename_list` | PATCH | `sync` | `/collections/{collection_id}/lists/{list_id}` | VERIFIED / SOURCE_CONFIRMED |
| `delete_list` | DELETE | `sync` | `/collections/{collection_id}/lists/{list_id}` | VERIFIED / SOURCE_CONFIRMED |
| `add_to_list` | POST | `sync` | `/collections/{collection_id}/lists/{list_id}/add_items` | VERIFIED / SOURCE_CONFIRMED |
| `remove_from_list` | POST | `sync` | `/collections/{collection_id}/lists/{list_id}/remove_items` | VERIFIED / SOURCE_CONFIRMED |
| `add_file` | POST | `sync` | `/collections/{collection_id}/items/{item_id}/add_file` | VERIFIED / SOURCE_CONFIRMED |
| `upload_file` | POST | `sync` | `/collections/{collection_id}/items/upload_file` | VERIFIED / SOURCE_CONFIRMED |
| `uploads_pending` | GET | `sync` | `/collections/{collection_id}/items/uploads_pending` | VERIFIED / SOURCE_CONFIRMED |
| `get_revisions` | GET | `sync` | `/collections/{collection_id}/items/{item_id}/revisions` | VERIFIED / SOURCE_CONFIRMED |
| `list_smartlists` | GET | `sync` | `/collections/{collection_id}/smartlists` | VERIFIED / SOURCE_CONFIRMED |
| `get_smartlist` | GET | `sync` | `/collections/{collection_id}/smartlists/{smartlist_id}` | VERIFIED / SOURCE_CONFIRMED |
| `create_smartlist` | POST | `sync` | `/collections/{collection_id}/smartlists` | VERIFIED / SOURCE_CONFIRMED |
| `update_smartlist` | PATCH | `sync` | `/collections/{collection_id}/smartlists/{smartlist_id}` | VERIFIED / SOURCE_CONFIRMED |
| `delete_smartlist` | DELETE | `sync` | `/collections/{collection_id}/smartlists/{smartlist_id}` | VERIFIED / SOURCE_CONFIRMED |
| `set_primary_file` | POST | `sync` | `/collections/{collection_id}/items/{item_id}/set_primary` | VERIFIED / SOURCE_CONFIRMED |
| `create_annotation` | POST | `sync` | `/collections/{collection_id}/bulk_single` | VERIFIED / SOURCE_CONFIRMED |
| `import_pmid` | POST | `sync` | `/collections/{collection_id}/items` | VERIFIED / SOURCE_CONFIRMED |
| `upload_pdf_flow` | FLOW | `sync` | `/collections/{collection_id}/items/{item_id}/add_file` | VERIFIED / SOURCE_CONFIRMED |
| `import_pdf_flow` | FLOW | `sync` | `/collections/{collection_id}/items/upload_file` | VERIFIED / SOURCE_CONFIRMED |
| `reader_metadata` | GET | `services` | `/reader/metadata` | VERIFIED / SOURCE_CONFIRMED |
| `watch_changes` | FLOW | `push` | `/bayeux` | VERIFIED / SOURCE_CONFIRMED |




所有已包装业务路径均有明确来源；新增批注由当前前端的 bulk_single 调用与 viewer-core 数据模型交叉确认。每个契约的原始 URL、版本、发现日期和 JS 字符偏移见 `readcube_client/endpoints.json`；公开 bundle 的 SHA-256 见 `research/public-assets.json`。

## 账户、List 和文献读取

当前版账户库列表使用 `GET services/collections`，响应为 `{"collections":[...]}`。Collection 的常见字段：`id`、`name`、`description`、`shared`、`organization_id`、`discoverable`、`user`。`shared` 等字段不能替代服务端权限检查。私人测试库创建后曾由账户列表再次读到。

`GET sync/collections/{collection_id}/lists` 返回 `{"lists":[...]}`。List 字段包括 `id`、`collection_id`、`name`、`parent_id`（缺省可视为根目录）、`item_ids`、`deleted`、`created`、`modified`、`seq`。普通 List 与 Smart List 不同；SDK 分别提供普通列表与 saved-query Smart List CRUD。

文献分页示例：

```http
GET /collections/C/items?size=50&sort[]=created,asc&client=webapp&client_id=&client_version=5.4.24
GET /collections/C/items?size=50&sort[]=created,asc&scroll_id=OPAQUE_CURSOR&client=webapp&client_id=&client_version=5.4.24
```

```json
{
  "status": "ok",
  "items": [{"id":"I","collection_id":"C","article":{"title":"Example"},"ext_ids":{"doi":"10.1234/example"},"user_data":{"tags":[],"notes":""},"files":[]}],
  "scroll_id": "OPAQUE_CURSOR",
  "total": 1
}
```

示例中的 ID/论文内容是结构示例，实际服务还返回其他字段。继续读取直到空页/无游标；如果服务报告的 total 尚未达到但游标丢失，则报错而非返回不完整库。某些实现可能连续返回相同 cursor，不能仅据此判定死循环；SDK 检查重复 item ID 和页数上限。

本轮以 `size=1` 完成真实分页：2 条有效记录，3 个 GET 请求（含末尾空页）。历史博客将下一页参数写作 `scoll_id`，但 Gist、Python 源码、当前前端和实测一致使用 **`scroll_id`**。当前前端仅在首次搜索请求附 query，后续分页省略；SDK 同样处理。

单篇响应：`{"item":{...}}`。文献字段分层：

| 字段 | 用途 |
|---|---|
| `id`, `collection_id` | 资源身份；不要用 DOI 替代 item ID 拼路径 |
| `article` | 标题、作者、年、期刊、摘要等书目信息 |
| `ext_ids` | DOI、PMID、arXiv、PMCID 等外部标识符 |
| `user_data` | 用户笔记、标签、评级等 |
| `files` | 文件名、sha256 等附件信息；原始附加字段保留 |
| `list_ids` | List 归属 |
| `seq`, `deleted` | 变更/删除相关字段；尚未据此还原完整增量协议 |

搜索默认通过完整读取后本地匹配：DOI 标准化并精确匹配，PMID 精确匹配，标题大小写无关子串匹配。前端有服务端 `query` 和其他搜索过滤参数，但复杂查询语法尚未系统验证，不将猜测的 `doi:` 语法作为新增去重的依赖。

## 新增 DOI / PMID 和手动文献

DOI 新增使用**顶层 ext_ids**，不是把标识符强行放到 `item.article`：

```http
POST /collections/C/items
Content-Type: application/json
```

```json
{"ext_ids":{"doi":"10.1038/nature12373"},"merge":true,"resolve":true,"resolve_files":false}
```

PMID 使用同一路径、单独验证过的契约：

```json
{"ext_ids":{"pmid":"23903748"},"merge":true,"resolve":true,"resolve_files":false}
```

两者返回 `item`；可能附带 `merged`。本轮以 DOI 创建记录，GET 确认 DOI 保存；PMID 请求实际合并回同一测试文献，并 GET 确认 PMID 和资源身份。

手动录入使用另一个请求形态：

```json
{"item":{"item_type":"article","article":{"title":"Synthetic test reference"}}}
```

可选元数据的全部字段和 item_type 枚举没有穷举验证。SDK 保留原始对象，不假装提供完全覆盖的书目模型。

客户端先查询目标库。已存在时返回 `{"created":false,"needs_review":false,"matches":[...]}`；多个同 DOI 项返回 `needs_review=true`。新增请求仍指定服务端 merge，降低搜索索引延迟和并发新增导致的重复。客户端不会自动删除/合并重复项目。

## 修改笔记、标签和元数据

| 操作 | JSON body | 语义 |
|---|---|---|
| `POST .../set_notes` | `{"notes":"Reading summary"}` | 整体替换笔记 |
| `POST .../set_tags` | `{"tags":["review"]}` | 整体替换标签 |
| `POST .../add_tags` | `{"tags":["temporary"]}` | 添加标签 |
| `POST .../remove_tags` | `{"tags":["temporary"]}` | 移除给定标签 |
| `PATCH .../items/I` | `{"item":{"article":{"title":"Updated"}}}` | 更新文献元数据 |

这些接口返回 `{"item":{...}}`，本轮分别通过再次 GET 核对。历史博客的 notes PATCH 不能直接当作当前主要实现；当前前端专门调用 `set_notes`。旧 notes PATCH 未单独重测。

对正式文献修改前先读取旧值。没有经过验证的条件写机制，不能承诺并发编辑不会覆盖。不要将用户要“添加摘要”直接理解为丢弃已有笔记；Agent 应先整理可审阅的新值。

## List CRUD 与归属

创建请求示例：

```json
{"list":{"id":"CLIENT_GENERATED_UUID","collection_id":"C","name":"Reading","parent_id":null}}
```

重命名：`PATCH /collections/C/lists/L`，body 为 `{"list":{"id":"L","collection_id":"C","name":"Renamed"}}`。

归属添加/移除分别为 `POST .../lists/L/add_items` 和 `POST .../lists/L/remove_items`，body 为 `{"item_ids":["I"]}`。响应为 `{"list":{...}}`。List 成员索引在写后可能延迟；验证脚本做有上限的只读等待，不重发写入。归属移除不会删除库中的参考文献。

本轮普通根 List 的创建、重命名、加入/移出和删除均验证。Smart List 的独立 `/smartlists` 路径也已实测 CRUD，body 为 `{"smartlist":{"id":"UUID","collection_id":"C","name":"Name","query":"text"}}`。修改保留 id/collection_id；删除后可返回 GET 404。深层 List、跨库成员与复杂查询语法仍未穷举验证。

## PDF 上传并关联到已有文献

完整流程已实际执行并核对 SHA-256。它不是单次 multipart 请求。

1. 读取用户合法本地 PDF，计算原始字节的 SHA-256。
2. `POST /collections/C/items/I/add_file`：

```json
{"file_name":"synthetic-test.pdf","file_size":687,"primary":false,"hash":"LOCAL_SHA256_HEX","resolve":false,"skip_resolve":true,"merge":false}
```

示例大小仅为示意，实际值必须由文件计算。若服务已知该 hash，可能直接返回 `item`；否则返回 `upload_id` 和 `upload_url`。

3. 向服务器返回的 HTTPS `upload_url` **PUT 原始文件字节**，`Content-Type: application/pdf`，不附加业务查询参数。本轮地址 host 为 `s3.amazonaws.com`；签名路径和查询参数不保存到公开证据或日志。S3 请求使用隔离的 HTTP 客户端，不携带 ReadCube Cookie。
4. GET `.../items/uploads_pending`，按 upload_id 读取状态。当前前端使用约 3 秒轮询；本轮返回的状态条目可直接按 upload_id 索引。
5. 状态 completed 时，核对服务器 hash 与本地 SHA-256，再 POST 相同 add_file 数据完成关联。
6. GET 文献，确认 hash 出现在 files[].sha256 或 primary_file_hash 字段。仅存储 PUT 成功不能标记关联完成。

SDK 对超时/服务端 failed/未知响应明确报错。写入不自动重试，超时后应先检查状态。文件默认 `primary=false`，不自动替换旧主文件。文件尺寸上限、各类订阅的存储限制、同一 PDF 的多文献关联没有穷举测试。

`import_pdf` 已实测直接新建文献：`POST .../items/upload_file` 使用 file_name/file_size/hash、resolve=true、skip_resolve=false、merge=true、user_data.tags=[]；其余 PUT/pending/reassociate 流程相同。新建后独立 GET 验证附件 hash。

补充 PDF 与 `POST .../items/I/set_primary` body `{"hash":"SHA256"}` 已实测。服务器 merge=true 对同 hash PDF 未保证唯一；SDK 先做 SHA-256 查重，再以按会话/库保存的近期 ID 进行独立 GET 确认，多个匹配返回 needs_review=true。此机制不提供跨进程事务锁或并发唯一性承诺。

## 批注与高亮

`GET .../items/I/annotations` 返回 `{"annotations":[...]}`。旧 Python 实现提取 id/type/text/note/color_id/page_start/item_id/user_name/modified；SDK保留原始对象。

已在合成 PDF 上真实新增便签和单页高亮，并精确读回字段；便签 note/color_id 修改与单独授权删除也通过。

新增使用 `POST /collections/C/bulk_single`：

```json
{"type":"item","action_name":"add_annotation","data":[{"id":"ITEM_ID","data":{"id":"ANNOTATION_UUID","type":"note","has_note":true,"note":"Synthetic note","page_start":0,"sha256":"PDF_SHA256","color_id":1,"position":[72,720]}}]}
```

SDK 限制为单篇、单条新增；检查 result 长度、saved 和返回文献 ID。`TextHighlight` 使用 type=highlight、page_start=page_end、rects=[[x,y,width,height]]，可选 text/note。页码为 0 基、原始页面单位、左下原点；已审阅颜色 ID 为 1/2/3/4/5/6/10。模型和辅助坐标转换见 `readcube_client/annotations.py`。

修改 `PATCH .../items/I/annotations/A`，已验证 note/color_id；删除使用同一路径 DELETE，仍要求精确 `DELETE A` 确认。未知批注类型、旋转/crop/user-unit 与跨页几何不做推断。字段读回不等于浏览器视觉位置已校验。

## 删除和权限

单篇删除：`DELETE /collections/C/items/I`；单 List 删除：`DELETE /collections/C/lists/L`。初轮对用户逐项确认的一篇合成测试文献和一个普通 List 删除；本轮另获授权删除一条合成便签和一个 Smart List。分别用 GET、tombstone/404 与列表确认目标缺失。无批量删除。

正式 SDK 需同时满足：当前会话下该操作 VERIFIED；库 ID 在 `write_collections` 中；`WriteAuthorization` 精确匹配该库且 authorized=true；删除额外要求 `confirmation="DELETE <精确目标ID>"`。MCP 也要求 Agent 取得人的单独删除授权。

## 同步、错误和历史接口

当前源码仍用 Bayeux 推送：握手、/meta/subscribe、/meta/connect，订阅 `/production/users/{id}` 和 `/production/collections/{id}/changes`。HTTP 同步客户端过滤 `sync_client_id`。本轮已验证握手/订阅/connect ack、受控 item updated 事件，以及断开期间修改由重新连接后的全扫描恢复。`watch_changes`/`watch_library` 使用通知触发扫描，并在初连、断线、定期与结束补偿。没有已确认的持久 cursor/replay，返回模式为 notification_assisted_full_scan。

`sync_changes` 返回 `mode=full_scan_local_diff`，added/changed/missing/total。它只在完整分页成功后原子替换本地指纹文件；任何页失败均保留旧快照。missing 不是已证实的服务端删除。

| 情形 | SDK 行为 |
|---|---|
| 401 / 403 | AuthenticationError；不自动绕过或重试认证 |
| 429 / 500 / 502 / 503 / 504 | GET 有限重试；尊重 Retry-After；长等待交由调用者 |
| POST/PATCH/DELETE/PUT 失败 | 不自动重试，防止重复写入 |
| HTTP 200 但非 JSON / status=error / error 字段 | ProtocolError，不当成成功或空库 |
| 响应字段缺失、分页中断、重复结果 | 显式异常 |
| 尚未验证或没有契约 | UnverifiedEndpointError / NotImplementedError 子类 |

这些是客户端错误处理能力；本轮没有对真实服务制造认证失败、限流或 5xx，相关负面路径由 MockTransport 测试覆盖。不能把客户端测试描述成实测了服务端错误码全集。

历史补充探测：`sync/collections/` 返回 301，Location 为 `https://services.readcube.com/collections`，验证了历史入口向当前 services 接口的迁移；`services/reader/metadata?doi=...` 返回 HTTP 200 JSON，顶层含 meta/citations/figures/references/options/supplements/total_pages，meta.doi 与请求 DOI 一致。metadata 已补充为正式门控 SDK 功能；历史 Collection 跳转仅记录，不引入重定向别名。当前公开登录 form 用于本地助手，SSO/MFA 和独立刷新协议尚未系统验证。

## 辅助接口与认证状态补充

`reader_metadata(doi)` 使用 `GET services/reader/metadata?doi=...`，保留 meta/references/figures 等原始字段并检查 meta.doi 精确匹配。`get_revisions(C,I)` 使用 `GET sync/collections/C/items/I/revisions`，返回数组；本次测试为空，不能视作增量游标或恢复历史能力。

`auth.session_status` 仅检查本地 Cookie；`validate_saved_session` 或 `login_local.py --check` 通过 GET collections 核验服务器状态，可安全保存服务器设置的 Cookie 更新。Cookie 身份变化会使旧验证证据失效。没有猜测独立 refresh-token 路径；失效时需正常重新登录。新版 password helper 先独立验证再保存，但其完整正常登录和 SSO/MFA/强制 CSRF 分支未在本轮重测，SDK login 仍显式报未验证。
