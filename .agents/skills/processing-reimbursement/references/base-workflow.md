# 多维表格处理

## 前提与身份

1. 调用 CLI 前，先阅读 `lark-shared`、`lark-wiki` 和 `lark-base` 技能。访问用户拥有的多维表格时使用 `--as user`。
2. 对知识库 URL，先检查 API schema，再解析链接。禁止将知识库 token 直接传给多维表格命令。

```powershell
lark-cli schema wiki.spaces.get_node
lark-cli wiki spaces get_node --params '{"token":"<wiki_token>"}' --as user
```

仅当 `node.obj_type` 为 `bitable` 时继续；其 `node.obj_token` 才是多维表格 token。

## 核对表结构

每次调用多维表格命令前，均需先阅读 `lark-base` 技能要求的命令参考。至少使用 `+table-list` 发现数据表，并对选定数据表使用 `+field-list`。将两份输出保存到任务的 `tmp/` 目录。

将下列语义角色映射到发现的精确字段名。字段不存在时应省略该角色，不得猜测。

| 角色 | 含义 | 用途 |
|---|---|---|
| `title` | 费用名称 | 全部证明材料页 |
| `sequence` | 多维表格“序号” | 可选；生成页头时使用其原始值，而非 PDF 页码 |
| `amount` | 金额（元） | 合计与证明材料页 |
| `category` | 费用类型 | 按类型筛选 |
| `review_status` | 审核结果 | 判断是否符合条件 |
| `receipt_status` | 报销/到账状态 | 判断是否符合条件与写回 |
| `date`、`counterparty`、`notes` | 补充信息 | 可选 PDF 元数据 |
| `invoice`、`order`、`payment` | 附件字段 | 材料检查与证明材料排版 |

计划写回前，确认所选状态字段是可写的存储字段，且目标值符合该字段类型。下拉字段的字符串必须与可用选项完全一致。

## 读取与筛选记录

调用 `+record-list` 前先阅读其参考文档。每次最多读取 200 条，并串行分页。将原始响应保存为 `records.json`。

默认符合条件指：发现的审核字段等于发现的“已审核”值，且到账状态字段为空。仅当用户明确要求纳入已上报条目时，才将“已上报，未到账”视为符合条件。状态名称或含义不一致时，展示候选项并询问用户，不得自行推断。

创建字段映射 JSON 文件，例如：

```json
{
  "sequence": "序号",
  "title": "费用名称",
  "amount": "金额（元）",
  "category": "类型",
  "review_status": "审核",
  "receipt_status": "到账情况",
  "date": "时间",
  "counterparty": "经手人/收款人",
  "notes": "备注",
  "invoice": "发票",
  "order": "订单页截图",
  "payment": "付款页截图"
}
```

随后生成并校验清单：

```powershell
python scripts/build_manifest.py --records tmp/records-0.json --records tmp/records-200.json --field-map tmp/field-map.json --out tmp/manifest.json --category "<scope>" --approved-value "<approved value>" --include-receipt-status "已上报，未到账"
python scripts/validate_manifest.py tmp/manifest.json
```

清单不能作为附件下载成功的证据；它只记录多维表格附件元数据和计划范围。

若用户要求“处理其余类型”，而已交付的类型不应重复生成，则在同一个计划命令中重复添加 `--exclude-category "<已处理类型>"`。该参数只从候选范围中排除精确匹配的类型，并在 `manifest.filters.excluded_categories` 中留下可审计记录；不得把此参数作为放宽审核或到账状态条件的替代品。

## 下载附件

多维表格附件值是结构化对象。应从清单中提取文件 token，显示名称不能作为可用 token。`drive +download` 不适用于单元格附件 token；使用 Drive 媒体下载 API，并在调用前阅读 `lark-cli api --help` 和飞书官方接口文档。

对于需要多维表格高级权限的附件，直接下载端点必须带 `extra.bitablePerm`：其中 `tableId` 为已发现的数据表 ID，`attachments` 的结构为“附件字段 ID → 记录 ID → 本次下载的 token 数组”。下载频率不高于每秒 4 个请求。

```powershell
$extra = @{ bitablePerm = @{ tableId = '<table_id>'; attachments = @{ '<field_id>' = @{ '<record_id>' = @('<file_token>') } } } } |
  ConvertTo-Json -Compress -Depth 8
$params = @{ extra = $extra } | ConvertTo-Json -Compress
lark-cli api GET "/open-apis/drive/v1/medias/<file_token>/download" --params $params --output '<destination>' --as user
```

范围和计划校验通过后，优先使用内置下载脚本。先在工作区根目录创建 `tmp/<本类型批次>/downloads/`；正式交付目录 `output/YYYYMMDD_类型名称_汇总金额/` 不承载临时文件。三个字段 ID 均来自刚读取的字段结构：

```powershell
python scripts/download_manifest_attachments.py `
  --manifest 'tmp/<本类型批次>/manifest.json' `
  --archive 'tmp/<本类型批次>/downloads' `
  --base-token '<base_token>' `
  --table-id '<table_id>' `
  --field-id 'invoice=<发票字段ID>' `
  --field-id 'order=<订单字段ID>' `
  --field-id 'payment=<付款字段ID>' `
  --as user --workers 4
```

该脚本的四个 worker 共用 0.25 秒的启动间隔，不会超过 4 次/秒；下载成功后才按文件签名重命名。任何下载失败、空文件、未知文件类型或已有同名稳定文件都会停止并列出问题，禁止自动覆盖或跳过。若接口不需要高级权限，也可使用飞书 Drive 媒体接口的临时下载链接批量端点。成功响应以 `code: 0` 判断，而非 `ok` 字段。每份下载材料先保存到根目录 `tmp/<本类型批次>/downloads/`，并分配稳定的中间文件名：

```text
{record_id}_invoice_0.pdf
{record_id}_order_0.jpg
{record_id}_payment_0.png
```

依据实际下载文件的文件签名或 MIME 类型确定扩展名；不得假定订单或付款附件一定是图片。生成 PDF 前，确认清单中每个附件 token 都有下载文件，并重新运行 `scripts/validate_manifest.py --materials tmp/<本类型批次>/downloads`。

下载校验通过后，必须将正式交付的原始附件导出到 `output/YYYYMMDD_类型名称_汇总金额/YYYYMMDD_类型名称证明材料_汇总金额元/`，与同名证明材料 PDF 一同位于该类型文件夹下。附件文件名为 `序号_费用名称_材料类型名称.扩展名`，其中序号来自清单中的多维表格“序号”字段，材料类型名称为“发票”“订单凭证”“付款凭证”。对同一记录的同类第 2 份及之后附件追加 `_2`、`_3`；费用名称中的 Windows 非法字符使用对应全角字符，不能静默删减或改写其他文字。

```powershell
python scripts/export_original_attachments.py `
  --manifest 'tmp/<本类型批次>/manifest.json' `
  --materials 'tmp/<本类型批次>/downloads' `
  --out 'output/YYYYMMDD_<类型名称>_<汇总金额>/<本类型批次>' `
  --dry-run
```

检查计划文件数和命名后，移除 `--dry-run` 执行。归档目录可以已存在，但必须为空；导出脚本拒绝覆盖其中的已有内容，并在复制后核对每个文件的字节数。证明材料 PDF 仍以根目录 `tmp/<本类型批次>/downloads/` 中的稳定命名材料为输入。

## 写回状态

写回状态属于外部修改，且只能基于本次已审核的 `manifest.json` 中的记录 ID。不得根据筛选条件重新查询后直接批量更新。

1. 阅读 `lark-base` 技能要求的记录值参考文档，重新执行 `+field-get`，确认状态字段是单选下拉字段、字段名正确、`multiple=false`，且精确目标值确实在选项中。
2. 以清单中的 `filters.category`、`filters.approved_value`、每条金额和（如存在）序号作为前置条件；写前必须逐条回读，确认类型、审核状态、金额、序号均未变，且状态仍为空。当前 CLI 的 `+record-get` 不支持 `--fields` 参数，应获取完整记录后在本地核对字段。
3. 先运行只读预检；预检发现任一条不符合时，停止且不写入。推荐使用内置脚本：

```powershell
python scripts/writeback_manifest_status.py `
  --manifest 'tmp/<本类型批次>/manifest.json' `
  --base-token '<base_token>' `
  --table-id '<table_id>' `
  --status-field-id '<状态字段ID>' `
  --status-field '<状态字段名>' `
  --category-field '<类型字段名>' `
  --review-field '<审核字段名>' `
  --amount-field '<金额字段名>' `
  --sequence-field '<序号字段名>' `
  --target-status '<精确状态值>' `
  --as user --dry-run
```

4. 向用户展示预检的记录 ID、条数、合计金额、目标字段和精确目标值。只有得到针对本次写回的明确确认后，才移除 `--dry-run` 重运行同一命令。脚本会在每条记录写入前再次检查前置条件，串行使用 `+record-upsert` 只修改该状态字段，并立即以 `+record-get` 回读验证；默认在写入之间等待 0.5 秒。
5. 状态改变、写入失败或回读不一致时，立即停止后续写入，分别报告成功和失败记录。存在部分成功时，不得声称任务已完成，也不得自动回滚已经回读成功的记录。

若写入后立即回读未看到目标值，先用 `+record-get` 独立确认实际状态；飞书可能短暂延迟，不要把“脚本尚未计入成功”误当成“未写入”而重复更新。当前脚本对新写入值最多做 5 次递增等待的回读。确认某些清单记录已经是精确目标值、其他条件仍匹配后，可以在同一清单上使用 `--dry-run --resume` 全量预检，再用 `--resume` 续写；脚本会跳过已是目标值的记录并分别报告 `already_target_record_ids` 与本次 `success_record_ids`。若状态是其他非空值，仍停止并报告，不得覆盖。

除非用户提出要求，否则不得将生成的 PDF 上传回多维表格或云盘。
