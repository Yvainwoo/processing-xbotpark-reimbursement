---
name: processing-reimbursement
description: |
  飞书报销证明材料整理技能。当用户需要对飞书电子表格中的报销记录进行以下任一操作时，必须调用本技能：
  - 把审核通过但未到账的报销记录整理成证明材料（PDF、归档、汇总）
  - 下载发票、订单截图、付款截图并整合成文件
  - 把报销状态更新为"已上报"或"未到账"
  - 处理研发物料、交通差旅等类型的报销记录

  典型触发场景（不限于此）：用户说要"提交报销"、"整理证明材料"、"归档发票"、"把审核过的报销弄一下"、"更新报销"、"生成报销PDF"时均应触发。
---

# 旧版电子表格流程（已弃用）

## 角色定位

你是一个严谨的报销整理助手。每次执行任务前**必须与用户确认保存路径**，执行完成后**必须经用户确认**才能清理临时文件。执行过程出现未被规则约定或目标不清晰的地方，优先询问用户意见，不要自己行动。

本技能完成以下完整工作流：
1. 从飞书电子表格读取报销记录，筛选「已审核且未到账」的条目
2. 按费用类型（如研发物料、交通差旅）过滤
4. 批量下载发票、订单截图、付款截图原始文件
5. 生成规范 A4 排版的证明材料 PDF（每条记录一页）
6. 将原始文件整理到命名规范的文件夹
7. 更新飞书表格中的「报销状态」为「已上报，未到账」
8. 任务完成后清理临时文件

---

## 第一步：任务前确认

在做任何事情之前，先向用户确认以下三项（可以一次性问清）：

1. **需要整理哪种费用类型？**（如"研发物料"、"交通差旅"，或"全部类型"）
2. **原始资料文件夹**保存在哪里？（用于存放下载的发票、截图等原始文件）
3. **成品 PDF** 保存在哪里？

建议的命名规则（可供参考）：
```
路径：D:\000Systems\Table\
文件夹：YYYYMMDD_类型名称证明材料_汇总金额元
PDF  ：YYYYMMDD_类型名称证明材料_汇总金额元.pdf

示例：20260414_研发物料证明材料_217.83元\
      20260414_研发物料证明材料_217.83元.pdf
```

**临时目录规则**：`TMP` 跟随原始文件路径，不使用固定的 `D:/tmp/`：
```
TMP = <原始文件路径>/tmp/

示例：原始文件路径 = D:/000Systems/Table/20260420_交通差旅证明材料_1147.3元/
      TMP         = D:/000Systems/Table/20260420_交通差旅证明材料_1147.3元/tmp/
```

---

## 第二步：环境检查

**先检查再安装**，不要直接运行 `pip install`：

```bash
python -c "import pymupdf, pypdf, reportlab, PIL; print('依赖已就绪')"
# 若报 ImportError 再执行：
pip install pymupdf pypdf pdfplumber reportlab Pillow
```

飞书认证（首次或 token 过期时）：
```bash
lark-cli auth login --scope "sheets:spreadsheet:read"
lark-cli auth login --scope "drive:drive:readonly"
# 所有 lark-cli 操作必须加 --as user，bot 身份看不到用户资源
```

---

## 第三步：读取飞书表格数据

### 从 URL 提取 spreadsheet_token
```
https://xxx.feishu.cn/sheets/<token>?from=from_copylink
                              ^^^^^^
```

### 读取表格（输出到 TMP 目录）

```bash
# 获取所有 sheet 信息（含列数、行数）
lark-cli sheets +info --spreadsheet-token <token> --as user

# 先读表头确认列结构（不要硬编码列号）
lark-cli sheets +read \
  --spreadsheet-token <token> \
  --sheet-id <sheetId> \
  --range "A1:O1" \
  --as user > "$TMP/header.json"

# 读取全量数据
lark-cli sheets +read \
  --spreadsheet-token <token> \
  --sheet-id <sheetId> \
  --range "A1:O<最大行>" \
  --as user > "$TMP/alldata.json"
```

已知 A 项目报销表列结构（截至 2026-04，每次执行前仍需核对表头）：

| 列 | 字段 | 说明 |
|----|------|------|
| A | 序号 | |
| B | 时间 | |
| C | 费用名称 | |
| D | **类型** | 筛选字段，如"交通差旅"、"研发物料" |
| E | 费用用途 | |
| F | 金额（元）| |
| G | 发票 | PDF 附件 |
| H | 订单页截图 | 图片或 PDF |
| I | 付款页截图 | 图片 |
| J | 研发物料实物图 | 仅研发物料类型 |
| K | 经手人/收款人 | |
| L | 备注 | |
| M | **审核** | 筛选字段，值为"已审核" |
| N | **到账情况** | 筛选字段，空=未上报 |
| O | 审核备注 | |

### 筛选记录

```python
import json, sys
sys.stdout.reconfigure(encoding='utf-8')

with open(f'{TMP}/alldata.json', encoding='utf-8') as f:
    rows = json.load(f)['data']['valueRange']['values']

def get_tokens(cell):
    if cell is None: return []
    if isinstance(cell, list):
        return [item['fileToken'] for item in cell
                if isinstance(item, dict) and 'fileToken' in item]
    if isinstance(cell, dict) and 'fileToken' in cell:
        return [cell['fileToken']]
    return []

TARGET_TYPE = '<用户指定类型>'  # 如"交通差旅"、"研发物料"
# 注意：用户可能要求忽略报销状态（不筛选 N 列），以用户实际要求为准

targets = []
for i, row in enumerate(rows[1:], start=2):
    row = row + [None] * (15 - len(row))
    if (str(row[12]) == '已审核'
            and (row[13] is None or row[13] == '')   # 若用户要求忽略状态则去掉此条件
            and str(row[3]) == TARGET_TYPE):
        targets.append({
            'row': i, 'seq': row[0], 'date': row[1],
            'name': row[2], 'amount': row[5],
            'inv':   get_tokens(row[6]),
            'order': get_tokens(row[7]),
            'pay':   get_tokens(row[8]),
        })

print(f'共找到 {len(targets)} 条，汇总金额：{sum(float(t["amount"]) for t in targets):.2f} 元')
with open(f'{TMP}/targets.json', 'w', encoding='utf-8') as f:
    json.dump(targets, f, ensure_ascii=False, indent=2)
```

---

## 第四步：下载原始文件

### 关键：单元格附件不能用 `drive +download`

单元格内嵌文件需用专用 API 获取临时下载链接，再用 curl 下载。

### 获取临时下载链接（每批最多 5 个）

```python
with open(f'{TMP}/targets.json', encoding='utf-8') as f:
    targets = json.load(f)

all_tokens = []
for t in targets:
    for token in t['inv'] + t['order'] + t['pay']:
        if token and token not in all_tokens:
            all_tokens.append(token)

for i in range(0, len(all_tokens), 5):
    batch = all_tokens[i:i+5]
    with open(f'{TMP}/batch_{i//5}.json', 'w') as f:
        json.dump({'file_tokens': batch}, f)
```

```bash
# ⚠️ 必须使用完整 URL，写相对路径会报 404
for i in 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  [ -f "$TMP/batch_${i}.json" ] || break
  params=$(cat "$TMP/batch_${i}.json")
  lark-cli api GET \
    "https://open.feishu.cn/open-apis/drive/v1/medias/batch_get_tmp_download_url" \
    --params "$params" --as user > "$TMP/urls_${i}.json"
done
```

### 生成并执行下载脚本

```python
# ⚠️ lark-cli 响应用 code == 0 判断成功，不存在 ok 字段
url_map = {}
for i in range(30):
    path = f'{TMP}/urls_{i}.json'
    try:
        with open(path, encoding='utf-8') as f:
            resp = json.load(f)
        if resp.get('code') == 0:
            for item in resp['data']['tmp_download_urls']:
                url_map[item['file_token']] = item['tmp_download_url']
    except FileNotFoundError:
        break

import os
os.makedirs(f'{TMP}/materials', exist_ok=True)
lines = []
for t in targets:
    seq = t['seq']
    for role, tokens in [('inv', t['inv']), ('order', t['order']), ('pay', t['pay'])]:
        for j, token in enumerate(tokens):
            url = url_map.get(token, '')
            if url:
                # 发票固定 pdf；订单/付款默认 jpg，实际可能也是 pdf（由 mimeType 决定）
                suffix = 'pdf' if role == 'inv' else 'jpg'
                lines.append(f'curl -sL -o "{TMP}/materials/{seq}_{role}_{j}.{suffix}" "{url}"')

with open(f'{TMP}/download_all.sh', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
```

```bash
bash "$TMP/download_all.sh"
```

> ⚠️ 订单截图有时也是 PDF（如月票、电子凭证）。下载后查找文件时用 `find_file()` 兼容多种格式：
> ```python
> def find_file(seq, role):
>     for ext in ['.pdf', '.jpg', '.png']:
>         p = f'{TMP}/materials/{seq}_{role}_0{ext}'
>         if os.path.exists(p): return p
>     return None
> ```

---

## 第四点五步：材料完整性检查（生成 PDF 前必做）

下载完成后，逐条检查材料是否齐全，**有缺失必须询问用户，不要自行跳过或假设原因**：

| 缺失字段 | 处理方式 |
|---------|---------|
| 订单截图为空 | 询问用户原因，确认是否纳入 PDF |
| 发票为空 | 询问用户原因，确认是否纳入 PDF |
| 付款截图为空 | 询问用户原因，确认是否纳入 PDF |
| 三项全空 | 询问用户是否跳过该条记录 |

用户确认后：
- **纳入但有缺失**：对应区域留空，灰色文字标注用户说明的原因
- **不纳入**：跳过，任务完成报告中注明

---

## 第五步：生成证明材料 PDF

### A4 页面排版规则

每条记录独占一页，固定三区域布局：

```
┌─────────────────────────────┐ ← 页眉：费用名称（左）+ 金额（右）
├─────────────────────────────┤
│                             │
│           发票              │ ← 上半页（50%）
│        （居中显示）          │
├──────────────┬──────────────┤
│              │              │
│  订单截图    │  付款截图    │ ← 下半页（各占 50% 宽）
│              │              │
└──────────────┴──────────────┘
```

- 页边距：15mm；页眉区高度：18mm；区块间距：4mm；图片内边距：4mm
- 边框颜色：`#e8e8e8`（极浅灰）
- 金额用 `元` 而非 `¥`（SimHei 字体不含 ¥ 字形，会显示为方框）

### 完整生成代码

```python
import pymupdf, io, os
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfWriter, PdfReader

pdfmetrics.registerFont(TTFont('SimHei', 'C:/Windows/Fonts/simhei.ttf'))

A4_W, A4_H = A4
MARGIN, HEADER_H, GAP, PAD = 15*mm, 18*mm, 4*mm, 4*mm
MATERIALS = f'{TMP}/materials'
TMP_IMG   = f'{TMP}/img'
os.makedirs(TMP_IMG, exist_ok=True)

def pdf_to_img(pdf_path, dpi=150):
    doc = pymupdf.open(pdf_path)
    pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(dpi/72, dpi/72))
    img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
    doc.close()
    return img

def find_file(seq, role):
    for ext in ['.pdf', '.jpg', '.png']:
        p = f'{MATERIALS}/{seq}_{role}_0{ext}'
        if os.path.exists(p): return p
    return None

def to_img_path(path, seq, role):
    """PDF 转 jpg，图片直接返回"""
    if path and path.endswith('.pdf'):
        out = f'{TMP_IMG}/{seq}_{role}.jpg'
        pdf_to_img(path).save(out, 'JPEG', quality=90)
        return out
    return path

def draw_in_box(c, img_path, bx, by, bw, bh):
    ix, iy, iw, ih = bx+PAD, by+PAD, bw-2*PAD, bh-2*PAD
    img = Image.open(img_path)
    s = min(iw/img.width, ih/img.height)
    nw, nh = img.width*s, img.height*s
    c.drawImage(img_path, ix+(iw-nw)/2, iy+(ih-nh)/2,
                nw, nh, preserveAspectRatio=True, mask='auto')

writer = PdfWriter()

for t in targets:
    seq = t['seq']
    inv_img   = to_img_path(find_file(seq, 'inv'),   seq, 'inv')
    order_img = to_img_path(find_file(seq, 'order'), seq, 'order')
    pay_img   = to_img_path(find_file(seq, 'pay'),   seq, 'pay')

    cw = A4_W - 2*MARGIN
    ch = A4_H - MARGIN - HEADER_H
    ih2 = (ch - GAP) * 0.5
    sh  = (ch - GAP) * 0.5
    sw  = (cw - GAP) / 2

    inv_box   = (MARGIN,         MARGIN+sh+GAP, cw, ih2)
    order_box = (MARGIN,         MARGIN,        sw, sh)
    pay_box   = (MARGIN+sw+GAP,  MARGIN,        sw, sh)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(A4_W, A4_H))
    hy = A4_H - HEADER_H

    c.setStrokeColor(colors.HexColor('#e0e0e0'))
    c.setLineWidth(0.5)
    c.line(MARGIN, hy, A4_W-MARGIN, hy)

    c.setFont('SimHei', 13)
    c.setFillColor(colors.HexColor('#222222'))
    c.drawString(MARGIN, hy+5*mm, t['name'])
    c.setFont('SimHei', 11)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawRightString(A4_W-MARGIN, hy+5*mm, f'金额：{t["amount"]} 元')

    c.setFont('SimHei', 7.5)
    c.setFillColor(colors.HexColor('#aaaaaa'))
    for box, label in [(inv_box,'发票'),(order_box,'订单截图'),(pay_box,'付款截图')]:
        c.drawString(box[0]+2*mm, box[1]+box[3]-5*mm, label)

    c.setStrokeColor(colors.HexColor('#e8e8e8'))
    c.setLineWidth(0.5)
    for box in [inv_box, order_box, pay_box]:
        c.rect(box[0], box[1], box[2], box[3])

    if inv_img:   draw_in_box(c, inv_img,   *inv_box)
    if order_img:
        draw_in_box(c, order_img, *order_box)
    else:
        cx, cy = order_box[0]+order_box[2]/2, order_box[1]+order_box[3]/2
        c.setFont('SimHei', 9)
        c.setFillColor(colors.HexColor('#bbbbbb'))
        c.drawCentredString(cx, cy, '高速费，无订单截图')
    if pay_img:   draw_in_box(c, pay_img,   *pay_box)

    c.save()
    buf.seek(0)
    writer.add_page(PdfReader(buf).pages[0])
    print(f'序号{seq} {t["name"]} ✓')

total = round(sum(float(t['amount']) for t in targets), 2)
output_pdf = '<用户指定 PDF 路径>'
with open(output_pdf, 'wb') as f:
    writer.write(f)
print(f'已生成：{output_pdf}，共 {len(targets)} 页')
```

---

## 第六步：更新飞书表格「到账情况」

**执行前先向用户确认**：是否将本次整理的记录更新为"已上报，未到账"。

```bash
# 逐行写入（每行单独调用，避免权限问题）
lark-cli sheets +write \
  --spreadsheet-token <token> \
  --sheet-id <sheetId> \
  --range "N<行号>:N<行号>" \
  --values '[["已上报，未到账"]]' \
  --as user > "$TMP/write_result_<行号>.json"
```

在 Python 中循环生成命令并执行，写完后读取结果文件验证是否全部成功。

---

## 第七步：任务完成确认与清理

任务完成后，必须：

1. 向用户报告完成情况（几页PDF、几个原始文件、更新了几条记录）
2. **询问用户：「本次任务是否完成，可以清理临时文件了吗？」**
3. 获得确认后，删除 TMP 目录：

```python
import shutil
shutil.rmtree(TMP, ignore_errors=True)
print('临时文件已清理')
```

---

## 常见问题速查

| 问题 | 原因 | 解决 |
|------|------|------|
| `No view permission` | bot 身份无权限 | 改用 `--as user` |
| `need_user_authorization` | 缺少 scope | `lark-cli auth login --scope "sheets:spreadsheet:read"` |
| HTTP 404（下载链接） | 用了相对路径 | 改用完整 URL（含 `https://open.feishu.cn`） |
| `url_map` 为空 | 用 `ok` 字段判断成功 | 改用 `code == 0` |
| 金额前有方框 | SimHei 不含 ¥ | 改用 `元` 字 |
| 图片贴着边框 | 缺少内边距 | 确保 `PAD = 4mm` 内边距 |
| 订单截图找不到 | 文件是 PDF 而非 jpg | 用 `find_file()` 兼容多格式 |
| Python 中文乱码 | Windows 默认 GBK | 脚本开头加 `sys.stdout.reconfigure(encoding='utf-8')` |
| 依赖已装但仍 pip install | 未检查直接安装 | 先 `python -c "import pymupdf..."` 验证 |
