# 报销清单

`build_manifest.py` 把本次读取的多维表格记录标准化为 `manifest.json`。清单是处理计划：用 `record_id` 标识记录，用十进制字符串保存金额，并记录筛选条件、入选记录及排除原因。它不代表附件已下载。

```json
{
  "filters": {"category": "交通差旅", "approved_value": "已审核"},
  "summary": {"record_count": 1, "amount_total": "1147.30"},
  "records": [{
    "record_id": "recxxxx",
    "sequence": "314",
    "title": "高铁票",
    "amount": "1147.30",
    "category": "交通差旅",
    "attachments": {
      "invoice": [{"token": "box1", "name": "invoice.pdf"}],
      "order": [{"token": "box2", "name": "order.png"}],
      "payment": [{"token": "box3", "name": "payment.png"}]
    }
  }],
  "excluded": [{"record_id": "recyyyy", "reason": "receipt_status_not_eligible"}]
}
```

运行 `validate_manifest.py` 核对记录 ID、金额、附件 token、记录数与合计金额，并拦截名称等字段中的 Unicode 替换字符 `�`；下载后再加 `--materials <下载目录>` 核对每份本地附件。缺少发票、订单或付款凭证时，先与用户逐项确认是否排除，或附说明纳入。清单及原始响应仅保存在工作区 `tmp/`，不作为交付文件。
