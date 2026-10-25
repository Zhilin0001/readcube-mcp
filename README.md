# ReadCube Papers API Client

基于真实请求验证的非官方 Python 3.11+ SDK 和本地 stdio MCP Server。

**2026-10-25：v0.2.0，38 项目录能力均已有实测证据，MCP 提供 27 个工具。** 在已有 CRUD 基础上，新增批注/高亮、Smart List CRUD、PDF 自动新建记录、主文件切换及实时事件监听。测试仍仅写入已授权的 `Codex API Test 2026-10-24` 库；实时同步采用通知加完整扫描，没有持久增量游标。

## 文件入口

- [API 文档](docs/readcube-api.md)：请求、参数、响应、证据和限制。
- [研究报告](docs/reverse-engineering-report.md)：源码出处、版本冲突、实测过程和未解决问题。
- [脱敏验证结果](docs/verification-results.json)：逐项状态；**不是**可用于解锁接口的运行时 ledger。
- `readcube_client/`：正式 SDK；`readcube_mcp/`：MCP Server。
- `scripts/verify_api.py`：显式选择研究模式的可执行验证程序。

## 安装

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[mcp,realtime,dev]'
```

开发环境为 macOS / Python 3.13，依赖快照见 `requirements-lock.txt`。代码声明支持 3.11+；本轮没有单独运行 3.11/3.12 解释器矩阵。MCP 使用 Python SDK **2.x** 的 `MCPServer`，不使用 1.x 的 `FastMCP` 导入路径。

## 认证与验证

```bash
.venv/bin/python scripts/login_local.py
.venv/bin/python scripts/verify_api.py
```

邮箱/密码在本地交互输入，不放在命令参数。当前公开页面已确认 password form；助手在空 Cookie jar 中单次登录，必须经账户 GET 验证后才覆盖旧会话。支持过期检测与脱敏错误分类，`scripts/login_local.py --check` 可只读核验。完整新版密码登录及 SSO/MFA/强制 CSRF 分支仍待实际正常登录验证。遇到 SSO/MFA/CAPTCHA 时停止，由用户正常完成。助手不会绕过验证。

会话文件默认 `~/.config/readcube-client/session.json`，权限必须为 `0600`。格式为 `{"cookies":[{"name":"...","value":"...","domain":".readcube.com","path":"/","secure":true,"expires":null}]}`，保留 Cookie 域和有效期。不得将实际值放进仓库、聊天或日志。

正式 SDK **只执行本机会话对应的已验证请求**。公开源码有实现不等于已验证；未经验证会抛出 `UnverifiedEndpointError`。文档里的成功记录不能替代本地验证文件。重新登录改变会话后需要重新验证。

写入研究测试需明确指定测试库名称：

```bash
.venv/bin/python scripts/verify_api.py --execute \
  --authorized-test-collection 'Codex API Test 2026-10-24'
```

该脚本先保存计划，创建私有测试库（如不存在），仅在其中新增 DOI 和合成文献、修改笔记/标签/List、上传合成 PDF；**不执行删除**。再次运行会新建合成测试对象。原始响应和对象 ID 在被 Git 忽略的 `research/private/` 内。

本轮已完成验证；当前本机可直接使用 `readcube.local.toml`。它仅允许写入测试库，允许上传 `research/private/` 内的文件。不要把此配置中的测试库 ID 换成正式库，除非用户另外授权。

## 最小 SDK 示例

```python
from readcube_client import ReadCubeClient, Settings, WriteAuthorization

settings = Settings.from_toml("readcube.local.toml")
with ReadCubeClient(settings) as client:
    collections = client.list_collections()
    collection_id = settings.write_collections[0]
    matches = client.find_by_doi("10.1038/nature12373", collection_id)
    print(matches)

    # 默认仅生成计划，零网络写入。
    plan = client.update_notes(collection_id, "ITEM_ID", "阅读摘要")
    print(plan.model_dump_json())

    # 仅在人类授权该具体修改后执行；notes 是整字段替换。
    # authorization = WriteAuthorization(collection_id=collection_id, authorized=True)
    # client.update_notes(collection_id, "ITEM_ID", "阅读摘要",
    #                     authorization=authorization, dry_run=False)
```

`find_by_title` 为本地不区分大小写的子串匹配，DOI/PMID 为精确匹配。检索会完整分页读取指定库；没有库 ID 时读取所有可访问库。新增按目标库查重，多个同 DOI 结果返回 `needs_review=true`，不会自动合并或删除。目标库外的相同 DOI 可通过不指定 collection_id 的查询发现，是否复制入目标库由用户决定。

新导入项目可能尚未进入服务端搜索索引；同一个 SDK 实例会记住新导入 ID 并通过 GET 核对，服务端 `merge=true` 不能保证所有情形均不重复。PDF 导入另用 SHA-256 扫描及会话/库隔离的 recent-ID 缓存查重；多个候选返回 `needs_review=true`。并发新增仍需人工核查。`resolve_files=false` 避免自动获取未知来源的全文。上传仅关联用户指定的合法本地 PDF。

## CLI

```bash
.venv/bin/python -m readcube_client capabilities
.venv/bin/python -m readcube_client collections
.venv/bin/python -m readcube_client search '10.1038/nature12373' --field doi
.venv/bin/python -m readcube_client --config readcube.local.toml add COLLECTION_ID '10.1038/nature12373'
```

最后一条默认 dry-run。执行写入须同时指定 `--execute --authorize-collection COLLECTION_ID`，配置文件也必须允许该库。所有业务输出为 JSON，错误返回 `ok=false` 及非零退出码。删除额外需要 `--confirm-delete 'DELETE ITEM_ID'`（List 使用 List ID）。禁止批量删除。

## MCP

```bash
.venv/bin/python -m readcube_mcp --config readcube.local.toml
```

只通过本地 stdio 提供服务。客户端配置示例 `examples/mcp-config.json` 中的绝对路径需按安装位置调整；本机已生成可直接使用的 `examples/mcp.local.json`（被 Git 忽略）。未自动改动 Codex/其他 Agent 的全局配置。

27 个工具包括：`readcube_capabilities`、`readcube_search_papers`、`readcube_get_paper`、`readcube_list_collections`、`readcube_list_lists`、`readcube_add_paper`、`readcube_upload_pdf`、`readcube_update_notes`、`readcube_update_tags`、`readcube_get_annotations`、`readcube_sync_library` 以及 List、Smart List、PDF 导入、批注 CRUD、metadata/revisions、实时监听和单条删除工具。

读操作直接执行；写操作默认 dry-run，执行须 `authorized=true, dry_run=false` 并匹配本机库白名单。Agent 必须先得到用户对具体修改的授权；工具参数不能替代人的授权。删除需要单独确认及精确的 `DELETE <id>`。MCP 上传必须显式配置 `upload_roots`，返回的 HTTPS 存储地址必须匹配 `upload_hosts`；S3 上传不携带 ReadCube Cookie。

## 配置

使用 `readcube.example.toml` 或 `.env.example`。优先级：环境变量 > `.env` > TOML > 默认值。数组类环境变量使用 JSON，例如：

```bash
export READCUBE_WRITE_COLLECTIONS='["TEST_COLLECTION_ID"]'
export READCUBE_UPLOAD_HOSTS='["sync.readcube.com","s3.amazonaws.com"]'
export READCUBE_UPLOAD_ROOTS='["/absolute/path/to/authorized/pdfs"]'
```

重试仅用于 GET；POST/PATCH/DELETE/存储 PUT 不自动重试。GET 尊重 `Retry-After`；等待超过 60 秒则返回错误，交由调用者稍后处理。认证失败和业务错误不返回空数组冒充成功。网络异常不包含响应正文、Cookie 或签名 URL；HTTP 请求的 INFO 日志被抑制。

## 测试

```bash
.venv/bin/python -m pytest -q
READCUBE_RUN_INTEGRATION=1 READCUBE_TEST_COLLECTION=TEST_COLLECTION_ID \
  .venv/bin/python -m pytest -q tests/test_integration.py
.venv/bin/python scripts/smoke_mcp.py --config readcube.local.toml
.venv/bin/ruff check readcube_client readcube_mcp scripts tests
.venv/bin/python -m build
```

本轮：**149 项单元/本地协议测试通过、2 项真实只读集成测试通过、27 工具的 MCP stdio 实测通过**。Mock 测试不会提升任何真实接口的验证级别。删除实测已单独获得用户对具体对象的授权，并核对服务器 tombstone/缺失结果。

## 已知边界

- 便签与单页高亮已有非空读回、新增、修改/删除验证；其他批注类型和特殊页面几何尚未覆盖。
- `sync_changes` 是**完整扫描后的本地差异检测**，不是已还原的服务端增量游标；`missing` 也可能由权限变化引起，不能直接解释为删除。
- PDF 新建文献、关联现有文献及主文件切换已验证；非 PDF 附件和上传额度仍未验证。默认 `primary=false`，仅显式 set_primary_file 改变主文件。
- 修改笔记/标签时先读取原值；暂未发现并验证 ETag/版本条件写机制，存在并发修改覆盖风险。
- 本项目不提供自动全文下载，不绕过机构订阅、验证码、MFA、访问权限或服务限流。

## 本轮新增用法

```python
from readcube_client.annotations import PageNote, TextHighlight

# 默认只生成单条批注请求计划；sha256 必须对应目标文献附件。
note = PageNote(sha256="PDF_SHA256", page_start=0,
                position=(72, 720), note="阅读便签")
# client.create_annotation(collection_id, item_id, note)
# client.import_pdf(collection_id, "/absolute/path/paper.pdf")
# client.create_smartlist(collection_id, "Methods", "methods")
# client.reader_metadata("10.1038/nature12373")
# client.get_revisions(collection_id, item_id)
# client.watch_changes(collection_id, duration=5)
```

示例的 PDF_SHA256 应替换为实际 64 位小写 hash。页码为 0 基；坐标采用原始页面单位、左下原点，rects 为 [x,y,width,height]。目前仅支持已审阅的便签与单页高亮。

`watch_changes` 需要 `[realtime]` 可选依赖，返回通知辅助的完整扫描结果；MCP 监听每次最多 30 秒。新脚本 `verify_extended.py`、`verify_annotations.py`、`verify_realtime.py` 默认 dry-run/只读，执行写入必须加 `--execute`。`verify_extended_delete.py` 还要求两个精确删除确认参数，不能用于未经授权的清理。

仍未覆盖：SSO/MFA 等特殊认证、持久增量游标、复杂共享角色、非 PDF 附件与上传限额、旋转/跨页批注、并发事务性唯一约束。详见研究报告的剩余边界。

## 生成 MCP 部署包

```bash
.venv/bin/python -m build
.venv/bin/python scripts/build_mcp_bundle.py
```

产物：`dist/readcube-mcp-0.2.0.zip`（无凭据分发包）与 `dist/readcube-mcp-0.2.0/mcp.local.json`（本机即用配置）。本机配置调用自动定位项目目录的 `start.local.sh`，不依赖客户端是否支持 cwd。部署说明见 [mcp/README.md](mcp/README.md)，27 个工具的 JSON Schema 随包保存为 tools.json。新机器/新会话需重新认证和验证，不继承本机证据。
