# 报销证明材料处理技能

本仓库提供 `processing-reimbursement` Codex 技能，用于从飞书多维表格整理报销记录、归档凭证，并生成证明材料与采购申请单。使用方法和处理规则见 [.agents/skills/processing-reimbursement/SKILL.md](.agents/skills/processing-reimbursement/SKILL.md)。

仓库仅保存技能脚本、说明和空白模板。运行时数据放在 `tmp/`，交付材料放在 `output/`；这两个目录不会提交到 Git。


## 如何使用

1. 在你的agent对话框引用报销skill，并输入“帮我处理一下报销，@你的报销表格链接”。
2. 等待agent链接你的表格并筛选“已审核”的报销条目。
3. 选择要处理的什么类型的报销。（也可以一次性全部将“已审核”的报销处理了）
4. 等待agent自己自动处理，有要补充或不明确的信息agent会自己来找你。
5. 处理完的报销的材料会放在 `output/`。（不放心材料准确性，可用飞书多维表格的筛选功能，进行人工核验，再进行下一步）
6. 向agent确认
    - 修改报销状态修改为“已审核，未到账”
    - 清理报销中的临时文件