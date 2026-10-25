# Bayeux collection change notifications

审阅与实测：2026-10-25。范围为已授权专用测试 Collection；本子任务没有执行写操作、删除或修改运行时验证 ledger。

## 当前源码证据

固定公开资产：[chunk-QD3Q3KF7.js](https://app.readcube.com/chunk-QD3Q3KF7.js)，Web 5.4.24，SHA-256 `53cb33e9f2b58fef18fc8eca5548eeab0e07087bbc18991821b1c7c4fbec2fe8`。以下偏移为该文件的字符位置：

| 偏移 | 契约 |
|---|---|
| 2327149 | `push:"https://push.readcube.com/bayeux"` |
| 2327511 | `wsChannelPrefix:"/production"` |
| 2337066 | handshake / connect / subscribe / disconnect 的 JSON 消息；ID 为 base36 |
| 2339476 | HTTP handshake 后建 WebSocket，发送 connect 与 subscribe，按 advice 维护心跳 |
| 2340464 | HTTP handshake 使用 Angular JSONP，参数名 `jsonp` |
| 2440996 | Collection channel 为 `/production/collections/{id}/changes`，读取 `data.changes` |

握手请求中 `message` 是一个 JSON 对象字符串；WebSocket 帧是 JSON 对象数组。服务器真实 JSONP 响应使用 `/**/callback(...)` 前缀。客户端只解析固定 callback 中的 JSON，从不执行 JS。

## 实测结果

GET 握手返回 HTTP 200，`successful=true`，支持 `websocket`，advice 为 `reconnect=retry`、`interval=0`、`timeout=25000`。两次独立建连均得到匹配 ID 的成功 subscribe 和 connect 响应；中间正常关闭后重新握手。第一次连接收到一个合法的 collection 变更批次，但本子任务没有发起该变更，不能据此声称完成受控因果验证。

脱敏原始结果：`research/private/realtime-readonly-probe.json`。不包含 Cookie、clientId、库 ID、签名地址或文献内容。根任务另外执行受控测试笔记更新并确认目标 ID/action 后，才可提升 `watch_changes` 运行时验证。

初始 connect 响应可延迟约 25 秒，符合服务端 timeout；subscribe 响应表示订阅就绪。因此 `BayeuxListener.connect()` 在 subscribe ack 后返回，`receive()` 继续验证 connect ack 和心跳期限。

## 实现与调用

新增独立 `readcube_client/realtime.py`，不修改原有 CRUD：

```python
from readcube_client.realtime import BayeuxListener, watch_library

with BayeuxListener(client, test_collection_id) as listener:
    # 根任务先保存 dry-run，再通过既有写授权更新专用测试 item。
    # 此处可进行授权的 notes 更新，然后读取已经排队的通知。
    changes = listener.receive(timeout=30)

for update in watch_library(client, test_collection_id, duration=30):
    print(update)  # JSON-ready: reason, mode, changes, delta
```

`watch_changes` 与其他操作一样使用会话及契约证据门控。可选依赖 `websockets>=15,<17`，真实测试版本 16.1.1；调用接口依据 [websockets 官方文档](https://websockets.readthedocs.io/en/stable/reference/sync/client.html)，SDK 内只在实际需要连接时加载连接器。

传给推送域的 Cookie 由已有 httpx CookieJar 按域、路径、secure、过期规则筛选；不复制其他域 Cookie。错误信息过滤底层网络异常，关闭 HTTP/WebSocket debug 日志；通知只返回 type/id/action，不泄露服务端 clientId。

## 同步语义与边界

这是通知辅助全量扫描，不是持久 delta cursor，也没有已证实的服务器事件重放。`watch_library` 在订阅建立、断线、重新订阅、通知、定期及正常结束时调用既有 `sync_changes` 完整扫描，继承其原子快照与失页保护。通知可合并并延迟约 1 秒扫描，最终一致的搜索索引仍由定期与结束扫描补偿。`missing` 只沿用已有“当前扫描未见”语义，不直接执行删除。

重连有上限和退避；服务器 advice `none` 不重连，`handshake` 触发新握手；拒绝订阅立即报错。单次 receive 最长 60 秒，watch 参数设有界限；HTTP/WS 建连和完整扫描分别受客户端超时约束，故 wall-clock 可能比 duration 多出正在进行的建连/扫描耗时。

28 项模块测试通过，覆盖 JSONP 注入拒绝、证据门控、Cookie 域隔离、匹配 ack、长 connect 先 subscribe、频道隔离、认证拒绝、心跳丢失、advice、异常脱敏、重连及全扫描补偿。真实网络丢包和服务器不发送通知无法证明绝不丢事件，因此保留定期完整扫描。
