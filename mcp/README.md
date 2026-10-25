# ReadCube MCP 0.2.0

Python 3.11+，本地 stdio MCP，27 个工具；包含当前 SDK 的全部依赖入口。安装包本身不含密码、Cookie、会话绑定验证记录或私人文献内容。

## 当前这台 Mac

主代理生成的 `mcp.local.json` 可直接导入支持本地 stdio 的 MCP 客户端。它调用 `start.local.sh`，自动进入当前项目并复用现有 Python 环境、会话和验证记录。无需重新登录。

当前已授权写入范围仍只有 `Codex API Test 2026-10-24` 测试库。写入默认 dry-run；删除需要单独确认。当前范围由项目中的 `readcube.local.toml` 决定，生成 MCP 不会扩大权限。源代码项目移动后需要重新生成本机配置。

## 无凭据分发包

解压 `readcube-mcp-0.2.0.zip`，在解压目录执行：

```bash
./install.sh
```

这会建立该目录自己的 `.venv`，安装随包 wheel 和 MCP/实时监听依赖（需联网获取依赖），然后生成本机 `mcp.local.json`。已有 `readcube.local.toml` 会保留；首次配置的写入白名单为空。安装不登录、不修改远端文献。

对于支持 `mcpServers` JSON 的客户端，将生成的 `mcpServers.readcube` 配置并入现有配置，不要覆盖其他 MCP 服务。stdio 由客户端按需启动，手动运行 start.sh 后等待输入是正常现象；协议 stdout 不应添加提示文本。

## 认证及验证边界

默认会话：`~/.config/readcube-client/session.json`；默认验证记录：`~/.config/readcube-client/verified.json`。两者仅在本机保留，不能放入分发包。

新机器或新会话不会继承当前账户的 VERIFIED 状态。可以用 `.venv/bin/python scripts/login_local.py` 在本地正常交互登录，再按 SDK 研究文档进行明确授权的验证；`scripts/verify_api.py` 默认只读验证 Collection 列表并生成后续计划。完整验证需要专用测试库和逐项语义检查，不能通过复制公开报告解锁接口。SSO/MFA 等特殊登录分支仍未完整实现。

当前 MCP 暴露的工具及 JSON Schema 见 `tools.json`。支持 Collection/List/Smart List、检索、DOI/PMID 导入、PDF 上传、新建 PDF 文献、笔记/标签、批注、高亮、metadata/revisions，以及通知辅助完整扫描。监听窗口最多 30 秒；完整扫描另需时间，客户端请求超时应留出余量。不提供持久增量游标。

## 检查连接

已有合法会话和 `list_collections` 验证记录时：

```bash
.venv/bin/python scripts/smoke_mcp.py --connection-config mcp.local.json
```

检查会启动真实子进程，完成 initialize、list_tools、capabilities、Collection 读取及零写入 dry-run。失败返回非零退出码。

此包为本地 stdio 服务，没有公开 HTTP 地址。客户端若只接受远端 HTTP MCP URL，不能直接导入这份本地配置。
