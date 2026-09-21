import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const ROLE = "实物图";
const TEMPLATE_SHEET = "模板";
const FIRST_ITEM_ROW = 7;
const LAST_ITEM_ROW = 27;
const TOTAL_ROW = 28;

function readOption(name, required = false) {
  const index = process.argv.indexOf(name);
  const value = index >= 0 ? process.argv[index + 1] : undefined;
  if (required && (!value || value.startsWith("--"))) {
    throw new Error(`Missing ${name}`);
  }
  return value;
}

function readRepeatedOption(name) {
  const values = [];
  for (let index = 0; index < process.argv.length; index += 1) {
    if (process.argv[index] === name && process.argv[index + 1]) values.push(process.argv[index + 1]);
  }
  return values;
}

function parseDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error("--application-date 必须为 YYYY-MM-DD");
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function hasPhysicalImage(value) {
  return Array.isArray(value) && value.length > 0;
}

async function physicalImageRecordIds(recordPaths) {
  const ids = new Set();
  for (const recordPath of recordPaths) {
    const payload = JSON.parse(await fs.readFile(recordPath, "utf8"));
    const data = payload?.data;
    const fieldIndex = data?.fields?.indexOf(ROLE);
    if (!Array.isArray(data?.record_id_list) || !Array.isArray(data?.data) || fieldIndex === -1) {
      throw new Error(`${recordPath} 缺少记录或“${ROLE}”字段`);
    }
    for (let index = 0; index < data.record_id_list.length; index += 1) {
      if (hasPhysicalImage(data.data[index]?.[fieldIndex])) ids.add(data.record_id_list[index]);
    }
  }
  return ids;
}

const templatePath = readOption("--template", true);
const manifestPath = readOption("--manifest", true);
const recordPaths = readRepeatedOption("--records");
const outputPath = readOption("--out", true);
const previewPath = readOption("--preview", true);
const applicant = readOption("--applicant", true);
const department = readOption("--department") ?? "项目部";
const applicationDate = parseDate(readOption("--application-date", true));
const expectedCategory = readOption("--category", true);
if (!recordPaths.length) throw new Error("至少提供一个 --records 文件");

const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
if (!Array.isArray(manifest.records)) throw new Error("清单缺少 records 数组");
const imageIds = await physicalImageRecordIds(recordPaths);
const items = manifest.records
  .filter((record) => record.category === expectedCategory && imageIds.has(record.record_id))
  .map((record) => ({ title: String(record.title ?? "").trim(), amount: Number(record.amount), category: record.category }));
if (!items.length) throw new Error(`没有“${ROLE}”有图的 ${expectedCategory} 记录`);
if (items.some((item) => !item.title || !Number.isFinite(item.amount))) throw new Error("入选记录缺少费用名称或有效金额");
const capacity = LAST_ITEM_ROW - FIRST_ITEM_ROW + 1;
if (items.length > capacity) {
  throw new Error(`入选 ${items.length} 条，超过模板单页 ${capacity} 条容量；先询问用户是否拆分为多份申请单`);
}
const total = items.reduce((sum, item) => sum + item.amount, 0);
const reason = [...new Set(items.map((item) => item.category))].join("、");

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(templatePath));
const sheet = workbook.worksheets.getItem(TEMPLATE_SHEET);

// 仅改动模板已有内容单元格；不改变字体、字号、颜色、边框、合并、行列尺寸或其他工作表。
sheet.getRange("C3").values = [[applicant]];
sheet.getRange("H3").values = [[department]];
sheet.getRange("C4").values = [[applicationDate]];
sheet.getRange("H4").values = [[applicationDate]];
sheet.getRange("C5").values = [[reason]];
for (let index = 0; index < capacity; index += 1) {
  const row = FIRST_ITEM_ROW + index;
  const item = items[index];
  if (!item) {
    sheet.getRange(`A${row}:I${row}`).clear({ applyTo: "contents" });
    continue;
  }
  sheet.getRange(`A${row}:I${row}`).values = [[
    index + 1,
    item.title,
    item.category,
    "个",
    1,
    item.amount,
    item.amount,
    item.amount,
    0,
  ]];
}
sheet.getRange(`G${TOTAL_ROW}:H${TOTAL_ROW}`).values = [[total, total]];

workbook.recalculate();
const inspection = await workbook.inspect({
  kind: "region",
  sheetId: TEMPLATE_SHEET,
  range: "A2:I33",
  maxChars: 12000,
  tableMaxRows: 40,
  tableMaxCols: 12,
});
console.log(inspection.ndjson);
const preview = await workbook.render({ sheetName: TEMPLATE_SHEET, range: "A2:I33", scale: 2, format: "png" });
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(path.dirname(previewPath), { recursive: true });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ selectedRecordCount: items.length, total: total.toFixed(2), outputPath }, null, 2));
