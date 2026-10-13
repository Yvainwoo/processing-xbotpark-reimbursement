param(
  [Parameter(Mandatory = $true)][string]$TemplateXlsx,
  [Parameter(Mandatory = $true)][string]$ManifestPath,
  [Parameter(Mandatory = $true)][string[]]$RecordsPath,
  [Parameter(Mandatory = $true)][string]$OutputXlsx,
  [Parameter(Mandatory = $true)][string]$Applicant,
  [string]$Department = '项目部',
  [Parameter(Mandatory = $true)][datetime]$ApplicationDate,
  [switch]$Overwrite
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$templatePath = (Resolve-Path -LiteralPath $TemplateXlsx).Path
$manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($null -eq $manifest.records) { throw '清单缺少 records 数组。' }

# 本批所有类型中实物图字段非空的记录汇总到同一份申请单。
$imageRecordIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
foreach ($recordPath in $RecordsPath) {
  $payload = Get-Content -LiteralPath $recordPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $data = $payload.data
  if ($null -eq $data -or $null -eq $data.fields -or $null -eq $data.record_id_list -or $null -eq $data.data) {
    throw "记录文件格式不完整：$recordPath"
  }
  $fieldIndex = [Array]::IndexOf([string[]]$data.fields, '实物图')
  if ($fieldIndex -lt 0) { throw ("记录文件缺少 [实物图] 字段：{0}" -f $recordPath) }
  for ($index = 0; $index -lt $data.record_id_list.Count; $index += 1) {
    # 空字段会在 PowerShell 中表现为单个 $null；过滤后再计数，避免误判为“有图”。
    $physicalImages = @($data.data[$index][$fieldIndex] | Where-Object { $null -ne $_ })
    if ($physicalImages.Count -gt 0) { [void]$imageRecordIds.Add([string]$data.record_id_list[$index]) }
  }
}

$items = @(
  $manifest.records |
    Where-Object { $imageRecordIds.Contains([string]$_.record_id) } |
    ForEach-Object {
      $title = ([string]$_.title).Trim()
      $amount = [decimal]$_.amount
      if (-not $title) { throw "记录 $($_.record_id) 缺少费用名称。" }
      if ($amount -lt 0) { throw "记录 $($_.record_id) 的金额无效。" }
      [pscustomobject]@{ Title = $title; Amount = $amount; Category = [string]$_.category; RecordId = [string]$_.record_id }
    }
)

if ($items.Count -eq 0) { throw '本批所选范围内没有 [实物图] 有图的记录。' }
$firstItemRow = 7
$lastItemRow = 27
$capacity = $lastItemRow - $firstItemRow + 1
if ($items.Count -gt $capacity) {
  throw "入选 $($items.Count) 条，超过模板单页 $capacity 条容量；请先确认同一份采购申请单的续页方式。"
}
$total = ($items | Measure-Object -Property Amount -Sum).Sum
$reason = (($items | Select-Object -ExpandProperty Category -Unique) -join '、')

$outputPath = [System.IO.Path]::GetFullPath($OutputXlsx)
if ((Test-Path -LiteralPath $outputPath) -and -not $Overwrite) { throw "拒绝覆盖已有文件：$outputPath" }
New-Item -ItemType Directory -Path ([System.IO.Path]::GetDirectoryName($outputPath)) -Force | Out-Null
Copy-Item -LiteralPath $templatePath -Destination $outputPath -Force

$excel = $null
$workbook = $null
try {
  $excel = New-Object -ComObject Excel.Application
  $excel.Visible = $false
  $excel.DisplayAlerts = $false
  $excel.ScreenUpdating = $false
  $workbook = $excel.Workbooks.Open($outputPath, 0, $false)
  $sheet = $workbook.Worksheets.Item('模板')

  # 只清除/写入内容，保留源模板中的字体、字号、边框、填充、合并、行高列宽、页面与打印设置。
  $sheet.Cells.Item(3, 3) = $Applicant
  $sheet.Cells.Item(3, 8) = $Department
  $sheet.Cells.Item(4, 3) = $ApplicationDate
  $sheet.Cells.Item(4, 8) = $ApplicationDate
  $sheet.Cells.Item(5, 3) = $reason
  for ($row = $firstItemRow; $row -le $lastItemRow; $row += 1) { $sheet.Range("A$row:I$row").ClearContents() }
  for ($index = 0; $index -lt $items.Count; $index += 1) {
    $row = $firstItemRow + $index
    $item = $items[$index]
    $values = @(($index + 1), $item.Title, $item.Category, '个', 1, [double]$item.Amount, [double]$item.Amount, [double]$item.Amount, 0)
    for ($column = 0; $column -lt $values.Count; $column += 1) {
      $sheet.Cells.Item($row, ($column + 1)) = $values[$column]
    }
  }
  for ($row = ($firstItemRow + $items.Count); $row -le $lastItemRow; $row += 1) {
    $sheet.Cells.Item($row, 9).ClearContents()
  }
  $sheet.Cells.Item(28, 7) = [double]$total
  $sheet.Cells.Item(28, 8) = [double]$total
  $workbook.Save()
} finally {
  if ($null -ne $workbook) { $workbook.Close($false) }
  if ($null -ne $excel) {
    $excel.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
  }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}

[pscustomobject]@{
  selected_record_count = $items.Count
  total = ('{0:F2}' -f $total)
  category = $reason
  output_path = $outputPath
} | ConvertTo-Json
