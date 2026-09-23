# 信息概要页规则

在生成每一种费用类型的报销证明材料时，同步生成一份独立的信息概要页 PDF。必须在信息概要页 PPT 模板中修改字段，再由 PowerPoint 的打印流程输出 A4 PDF；不得另行编写自绘 PDF 代码，也不得追加到证明材料 PDF。

## 内容来源

| 内容 | 来源 | 缺失处理 |
|---|---|---|
| 项目名称 | PPT 模板中的已填项目名称 + 本次处理的费用类型 | 使用 <模板项目名称>（<费用类型>）；项目名称为空或为占位值时询问用户。 |
| 报销总金额 | 已通过清单校验的该类型金额合计 | 使用清单金额；保留实际小数位，沿用模板的金额字段格式。 |
| 报销人 | 信息概要页 PPT 模板中的已填实际值 | 为空或占位值时询问用户。 |
| 报销人电话 | 信息概要页 PPT 模板中的已填实际值 | 为空或占位值时询问用户。 |

读取模板时应检查所有幻灯片文本。`XXX`、空白和“姓名”“电话”等字段名不构成可用信息。模板中的实际项目名称可复用；金额占位值不可沿用。

## 输出与检查

- 文件名：`output/YYYYMMDD_<类型名称>_<汇总金额>/信息概要页_<类型名称>_<汇总金额>元.pdf`，类型文件夹金额不加“元”。
- 页面：单页 A4。PPT 幻灯片自身尺寸保持不变，打印输出时适应 A4 纸张。
- 复制模板到 `tmp/` 后修改，禁止覆盖原始 PPT 模板；在 PowerPoint 中选择 PDF 打印机、A4 纸张、整页幻灯片和适应纸张大小后打印。不得使用“另存为 PDF”，以免输出保留 16:9 页面尺寸。
- 只可替换字段文本；不得修改任何文字的字号、字体、颜色、下划线、位置、文本框尺寸或整体版式。若项目名称追加费用类型后换行、溢出或遮挡，停止并询问用户是调整填写内容，还是由用户先修改 PPT 模板。
- 生成后渲染该 PDF，检查四项内容完整、文字未截断、金额与清单相符、模板品牌元素和版式未改变，且未出现附件或证明材料页。

对当前模板可采用快速且可验证的替换方式：复制 PPTX 至 `tmp/summary-a4-print/`，仅将 `儿童手工` 替换为 `儿童手工（<费用类型>）`、将 `XXX` 替换为汇总金额。替换后，把两处文字还原并与源模板的 `ppt/slides/slide1.xml` 逐字比较；不一致即停止。该校验能确保未改动字号、字体、位置、文本框或其他版式。随后只通过 PowerPoint 的“打印”流程生成 PDF，并渲染该单页进行检查。

优先调用内置脚本，避免 PowerPoint 在“保存”时重写文本运行属性：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/print_summary_page.ps1 `
  -TemplatePptx assets/信息概要的模版.pptx `
  -WorkPptx 'tmp/<本类型批次>/summary-a4-print/信息概要页_<类型名称>_<金额>元.pptx' `
  -OutputPdf 'output/YYYYMMDD_<类型名称>_<金额>/信息概要页_<类型名称>_<金额>元.pdf' `
  -Category '<类型名称>' -Amount '<金额>'
```

该脚本只在复制出的 `ppt/slides/slide1.xml` 内替换上述两段文字，之后由 PowerPoint **只读打开**并打印；不得将工作副本交给 PowerPoint 保存。打印前确认 Windows 默认打印机为 `Microsoft Print to PDF` 且纸张规格为 A4。PowerPoint 对横向幻灯片会按原生“适应纸张”行为生成横向 A4；只要页尺寸为 A4 且未改变幻灯片尺寸、文字或版式，即为合格输出。不得为了强制纵向而修改 `Presentation.PageSetup`、幻灯片尺寸或模板元素。

有多个类型时，一次提供 UTF-8 JSON 数组并运行批量脚本；`work_pptx` 与 `output_pdf` 使用完整路径。脚本先检查所有输出路径与替换后的 XML，再只启动一次 PowerPoint 顺序打印。现有 PDF 不会被覆盖。

```json
[
  {"category":"办公用品","amount":"125.83","work_pptx":"<工作区>/tmp/<办公用品批次>/summary-a4-print/信息概要页_办公用品_125.83元.pptx","output_pdf":"<工作区>/output/YYYYMMDD_办公用品_125.83/信息概要页_办公用品_125.83元.pdf"},
  {"category":"交通差旅","amount":"873.49","work_pptx":"<工作区>/tmp/<交通差旅批次>/summary-a4-print/信息概要页_交通差旅_873.49元.pptx","output_pdf":"<工作区>/output/YYYYMMDD_交通差旅_873.49/信息概要页_交通差旅_873.49元.pdf"}
]
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts/print_summary_pages.ps1 `
  -TemplatePptx assets/信息概要的模版.pptx -JobsJson '<任务 tmp>/print-jobs.json'
```
