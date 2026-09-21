param(
  [Parameter(Mandatory = $true)][string]$InputXlsx,
  [Parameter(Mandatory = $true)][string]$OutputPdf,
  [string]$SheetName = '模板',
  [ValidateRange(1, 60)][int]$WaitSeconds = 20
)

$inputPath = (Resolve-Path -LiteralPath $InputXlsx).Path
$outputPath = [System.IO.Path]::GetFullPath($OutputPdf)
if (Test-Path -LiteralPath $outputPath) { throw "拒绝覆盖已有 PDF：$outputPath" }
$excel = $null
$workbook = $null
try {
  $excel = New-Object -ComObject Excel.Application
  $excel.Visible = $false
  $excel.DisplayAlerts = $false
  $excel.ScreenUpdating = $false
  # Excel 的 ActivePrinter 使用系统语言相关的连接词（例如“在”或“on”）。
  # 当前会话已以 Microsoft Print to PDF 为活动打印机时直接复用完整标识，避免自行拼接端口失败。
  $activePrinter = [string]$excel.ActivePrinter
  if (-not $activePrinter.StartsWith('Microsoft Print to PDF ')) {
    throw "当前 Excel 活动打印机不是 Microsoft Print to PDF：$activePrinter"
  }
  $workbook = $excel.Workbooks.Open($inputPath, 0, $true)
  $worksheet = $workbook.Worksheets.Item($SheetName)
  # 严格沿用模板的样式和页面设置：这里不修改纸张、缩放、页边距或任何单元格。
  # 仅在这个只读打印会话中限定表格区域，避免模板工作表的尾部空行输出第二张空白 A4；不写回 XLSX。
  # 必须从第 1 行开始，模板的 Logo 与地址是锚定在第 1 行的浮动图片，不能被打印区域排除。
  $worksheet.PageSetup.PrintArea = '$A$1:$I$33'
  $missing = [System.Reflection.Missing]::Value
  [void]$worksheet.GetType().InvokeMember(
    'PrintOut',
    [System.Reflection.BindingFlags]::InvokeMethod,
    $null,
    $worksheet,
    [object[]]@($missing, $missing, 1, $false, $activePrinter, $true, $false, $outputPath, $false)
  )
  # Microsoft Print to PDF 会在 PrintOut 返回后异步写入文件，短暂等待非空文件完成落盘。
  $deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
  while ((-not (Test-Path -LiteralPath $outputPath) -or (Get-Item -LiteralPath $outputPath).Length -eq 0) -and [DateTime]::UtcNow -lt $deadline) {
    Start-Sleep -Milliseconds 500
  }
  if (-not (Test-Path -LiteralPath $outputPath) -or (Get-Item -LiteralPath $outputPath).Length -eq 0) {
    throw 'Excel 打印流程未生成有效 PDF'
  }
} finally {
  if ($null -ne $workbook) { $workbook.Close($false) }
  if ($null -ne $excel) {
    $excel.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
  }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}
