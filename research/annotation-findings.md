# 批注契约补充证据

研究日期：2026-10-25。本文记录源码证据；真实验证状态以运行时 ledger 及主报告为准。本子任务未执行任何真实写入或删除。

## 可落实的新增请求

当前 5.4.24 前端提供了已有精确调用者的新增批注路径，可将此前 `create_annotation` 的 UNKNOWN 收窄为 SOURCE_CONFIRMED：

```http
POST https://sync.readcube.com/collections/{collection_id}/bulk_single
```

```json
{
  "type": "item",
  "action_name": "add_annotation",
  "data": [{
    "id": "target-item-id",
    "data": {
      "id": "client-generated-annotation-uuid",
      "type": "note",
      "has_note": true,
      "note": "Synthetic API note",
      "page_start": 0,
      "sha256": "attached-file-sha256",
      "color_id": 1,
      "position": [72, 720]
    }
  }]
}
```

外层 `id` 为文献 ID，内层 `id` 为批注 ID；`sha256` 指定文献所关联的文件。不要把批注内部的 `item_id` 发送到服务端，前端会将其抽取到外层后删除。虽然接口名含 bulk，SDK builder 只构造单个文献、单条批注。

`chunk-QD3Q3KF7.js` 字符偏移 2450223 的 `bulkCreateAnnotations(e,r,n)` 明确构造上述地址/信封，将输入按 bulkRequestSize 切分（此 SDK 不提供批量写入口）。返回解析为 `result` 数组，只接受 `saved` 且存在 `object` 的条目。真实验证时需检查数组长度、saved、返回文献 ID，并独立调用 annotations GET 找到内层 ID。

`chunk-JCLW3CJS.js` 的 Mendeley 导入调用者（`convertAnnotations(){`，约偏移 1032960）明确发出以下两种数据：

| type | 数据字段 |
|---|---|
| note | id, type, has_note=true, item_id, note, page_start, sha256, color_id, position |
| highlight | id, type, has_note=false, item_id, page_start, page_end, sha256, color_id, rects |

PDF 内容仍须与 sha256 对应，页码须存在。调用成功不证明视觉位置正确；需要独立读回几何字段，并在已知尺寸的合成 PDF 上核对页面位置。

## 当前 reader 的几何依据

主前端 `chunk-JCLW3CJS.js` 在偏移 416581 明确依赖 `@readcube/viewer-core` `^13.7.0`，在 417011 使用 `https://pkg.readcube.com/@readcube/viewer-core`，去掉版本前导非数字字符并加载 `index.umd.js`。因此下载了明确引用的公开资产：

- URL: https://pkg.readcube.com/@readcube/viewer-core@13.7.0/index.umd.js
- HTTP 200；传输内容为 gzip，解压后的文件保存为被 Git 忽略的 `research/sources/viewer-core-13.7.0.js`。
- 传输字节 SHA-256：`9bdeefad152eb4a386c256579114cf03a6e36b7f72dfc507d392f6e1b7f9145a`。
- 解压字节数：1111167；SHA-256：`9b1e6d6e6b50dbc97d6346abd70f674dd147aed99979073ee8eaef6976c95b38`。
- 未执行此第三方脚本；仅静态检查明确函数。

以下偏移均为解压后文本的字符偏移（而非 UTF-8 字节/行号）：

| 偏移 | 函数/常量 | 直接证明 |
|---|---|---|
| 882150 附近 | Ml=2 / COLOR_RANGES | 几何保留两位；note/highlight UI 颜色为 1,2,3,4,5,6,10 |
| 884706 | function TS | sync point -> display point: x=point[0], y=originalHeight-point[1] |
| 884771 | function SS | display point -> sync point: [x, originalHeight-y] |
| 884979 | function kS | sync rect -> display rect: [x, originalHeight-y-height,width,height] |
| 885071 | function e8 | display rect -> sync rect: [left,originalHeight-top-height,width,height] |
| 940800 附近 | function Gz | highlight 默认 page_start/page_end 都为 page.index-1；支持 note/has_note/text |
| 1040843 | function f7 | note 默认 type=note，color_id=1，page_start=page.index-1，position 数组 |

坐标是未旋转原始页面单位，左下角为原点；不是屏幕像素，也不是 [0,1] 比例。页码为 0 基；rects 数组元素为 [x,y,width,height]，不是 [x1,y1,x2,y2]。SDK 不猜测页面旋转、crop box 和 PDF user-unit 转换。跨页高亮应分成多个已知页的单页批注；本实现拒绝未审阅的跨页矩形契约。

## 修改与删除

主前端 `chunk-QD3Q3KF7.js`：

- offset 2443105，`patchAnnotation(e,r,n,a)`：PATCH `/collections/{cid}/items/{iid}/annotations/{aid}`，直接发送 raw patch `a`，之后 GET 文献。
- offset 2442949，`deleteAnnotation(e,r,n)`：DELETE 相同地址，之后 GET 文献。

现有 SDK 路径与 envelope 符合源码。可以在合成批注上测试 `{note: "updated"}` 并以 annotations GET 读回相同 ID 的新文字；避免用 metadata PATCH 代替批注 PATCH。删除必须先获得对该批注精确 ID 的单独授权，再读回确认它消失且另一条批注仍存在。

## 实现与测试

`readcube_client/annotations.py` 新增 PageNote、TextHighlight、annotation_data、single_annotation_body，另提供明确限定未旋转原始页面单位的两个坐标转换辅助函数。仅校验写入请求，不用于裁剪服务端返回的未知字段。

`tests/test_annotations.py` 共 17 项通过：单条信封与文件/文献分层、坐标变换、note 标志、空矩形/负数/NaN/Infinity、无效 hash、混合类型字段、跨页拒绝。此测试不表示任何真实 API 写入成功，也不修改运行时 VERIFIED 状态。
