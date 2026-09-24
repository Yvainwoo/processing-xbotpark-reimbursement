# 飞书多维表格：读取、下载与写回

本页用于访问飞书 Base。执行命令前阅读 `lark-shared`、`lark-wiki` 和 `lark-base` 的当前命令参考；访问用户表格使用 `--as user`。示例中的 `scripts/` 指本 skill 的脚本目录，`tmp/` 和 `output/` 指工作区根目录。

## 找到数据表

知识库链接先解析节点，确认 `obj_type=bitable`，再将 `obj_token` 作为 Base token；不能直接使用 wiki token。

```powershell
lark-cli schema wiki.spaces.get_node
lark-cli wiki spaces get_node --params '{"token":"<wiki_token>"}' --as user
```

列出数据表和目标表的字段，核对字段类型、下拉选项与附件值。建立“语义角色 → 实际字段名”的映射，不使用旧表列号。此任务需要 `sequence`（序号）、`title`（费用名称）、`amount`（金额）、`category`（类型）、`review_status`（审核）、`receipt_status`（报销状态）以及 `invoice`、`order`、`payment` 三类附件；`date`、`counterparty`、`notes` 可选。字段名以本次读取结果为准。

```powershell
lark-cli base +table-list --base-token <obj_token> --as user
lark-cli base +field-list --base-token <obj_token> --table-id <table_id> --as user
```

```json
{
  "sequence": "序号", "title": "费用名称", "amount": "金额（元）",
  "category": "类型", "review_status": "审核", "receipt_status": "报销状态",
  "invoice": "发票", "order": "订单页截图", "payment": "付款页截图"
}
```

## 读取和筛选

每页最多读取 200 条，串行翻页；同一批只读取一次全量记录，并把每页原始响应、表结构和字段映射以 UTF-8 保存在 `tmp/`。当前 `+record-list` 的列式响应含 `data.fields`、`data.data` 和 `data.record_id_list`，`build_manifest.py` 可直接读取，不必手工逐行转换。默认入选条件为“已审核”且报销状态为空；仅在用户明确要求时才额外纳入“已上报，未到账”。字段选项不同或含义不明时先核对，不能猜测。

```powershell
lark-cli base +record-list --base-token <obj_token> --table-id <table_id> --limit 200 --offset 0 --as user
```

Windows 控制台打印中文出现乱码时，先按 UTF-8 读取保存的 JSON 和清单，检查实际字段值及是否含替换字符 `�`；不要仅凭终端显示就重新下载全部记录或逐条调用 `+record-get`。只有文件中的数据确实损坏，才针对受影响记录重取并重新校验清单。

用 `build_manifest.py` 将原始响应转为清单，再运行 `validate_manifest.py`。多个分页文件可重复传 `--records`；处理单一类型用 `--category`，处理全部类型则省略。只有用户明确要求纳入已上报记录时，才加 `--include-receipt-status '已上报，未到账'`。处理“其余类型”时，可重复加 `--exclude-category` 精确排除已交付类型；它不改变审核或到账条件。清单结构见[报销清单](manifest.md)。

## 下载和归档附件

从清单读取附件 token，不把显示名称当作 token。单元格附件不能使用 `drive +download`；按当前飞书文档使用媒体下载接口。需要高级权限时，请求附上 `extra.bitablePerm`，其中 `tableId` 为数据表 ID，`attachments` 按“附件字段 ID → 记录 ID → 本次 token 数组”组织。接口成功以 `code: 0` 判断。下载请求总频率不超过每秒 4 次。

优先调用 `download_manifest_attachments.py`，传入清单、Base token、表 ID，并分别传 `--field-id invoice=<字段ID>`、`order=<字段ID>`、`payment=<字段ID>`，使用 `--as user --workers 4`，将文件写到 `tmp/<本类型批次>/downloads/`。脚本按 `{record_id}_{role}_{index}` 稳定命名，并根据文件签名确定扩展名；下载失败、空文件、未知格式或重名时停止，不跳过。下载后用 `validate_manifest.py --materials <下载目录>` 核对每个 token。若用户明确同意保留凭证缺失的记录，才加 `--allow-missing-evidence`，并在 PDF 中提供对应的缺失说明。

校验通过后，先以 `export_original_attachments.py --dry-run` 核对数量和名称，再导出到：

```text
output/YYYYMMDD_类型_汇总金额/YYYYMMDD_类型证明材料_汇总金额元/
```

每份文件名为 `序号_费用名称_材料类型名称.扩展名`；同一记录同类的第二份起加 `_2`、`_3`。费用名称中的 Windows 非法字符换成对应全角字符，其余文字不改。目标目录必须不存在或为空；证明材料 PDF 仍使用 `tmp/` 中的稳定下载文件作输入。

## 写回状态

完整报销整理任务在资料生成与核验后，准备本批已审核清单中的记录 ID；写回前必须取得用户对本批状态变更的明确确认。只读核算、预览、单项产出或用户明确要求不写回时跳过。目标为“报销状态”字段的“已上报，未到账”；写前重新读取字段，确认它是可写的单选存储字段，且目标值是精确选项。预检应列出记录 ID、条数、合计金额、字段和值，并连同交付清单给用户确认；目标值不存在或用户另有指定时先核对，不得近义替换。

先运行 `writeback_manifest_status.py --dry-run`。脚本需要清单、Base token、表 ID、状态字段 ID 和名称、类型/审核/金额/序号字段名、目标状态及 `--as user`。预检逐条回读，确认类型、审核、金额、序号未变且当前状态符合预期；任何一条不符都停止。预检全通过且用户明确确认本批写回后，去掉 `--dry-run` 写入，逐条回读验证；不要按筛选条件直接批量更新。当前 CLI 的 `+record-get` 应读取完整记录后在本地核对，不传 `--fields`。

若部分成功或回读短暂延迟，先独立查询实际状态。确认已写入条目确为目标值、其他条件仍匹配后，对同一清单运行 `--dry-run --resume`，通过后再用 `--resume` 续写；脚本会跳过已成功项。遇到其他非空状态、写入失败或回读不一致时，停止并分别报告成功与失败项，不自动覆盖或回滚。最终回复必须同时列出交付文件和状态写回结果；不能只报告脚本执行成功。
