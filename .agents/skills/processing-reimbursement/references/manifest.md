# 清单格式

`scripts/build_manifest.py` 会生成如下结构的 JSON 计划：

```json
{
  "generated_at": "2026-09-20T01:02:03+00:00",
  "filters": {"category": "交通差旅", "approved_value": "已审核"},
  "summary": {"record_count": 1, "amount_total": "1147.30"},
  "records": [
    {
      "record_id": "recxxxx",
      "sequence": "314",
      "title": "高铁票",
      "amount": "1147.30",
      "category": "交通差旅",
      "date": "2026-09-18",
      "counterparty": "姓名",
      "notes": "出差",
      "attachments": {
        "invoice": [{"token": "boxxxx", "name": "invoice.pdf"}],
        "order": [],
        "payment": [{"token": "boxyyy", "name": "pay.png"}]
      }
    }
  ],
  "excluded": [{"record_id": "recyyyy", "reason": "receipt_status_not_eligible"}]
}
```

将记录 ID（而非标题或行号）作为稳定标识。金额在计划阶段始终使用十进制字符串，以避免二进制浮点误差。`validate_manifest.py` 会校验标识、金额、附件 token；提供 `--materials` 时，还会检查每个计划附件是否已按预期稳定前缀下载到本地。

清单可能包含报销信息。只能保存在本次任务的 `tmp/` 目录；除非用户要求，否则不得将其发送到聊天或上传至其他位置。
